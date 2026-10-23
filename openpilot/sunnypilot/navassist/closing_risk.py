"""Experimental front-visible closing-risk observer. Never authorizes or actuates a lane change."""
import math
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    max_age_ns: int = 800_000_000
    window_ns: int = 2_000_000_000
    min_span_ns: int = 800_000_000
    min_samples: int = 5
    min_confidence: float = .5
    max_fit_rmse_m: float = .8
    min_closing_mps: float = 2.
    max_relative_mps: float = 25.
    max_gap_exhaustion_s: float = 4.
    confirm_ns: int = 200_000_000

def finite(value):
    return type(value) in (int,float) and math.isfinite(value)

class ClosingRiskObserver:
    def __init__(self, config=Config()):
        self.config=config
        self.stream=None
        self.last_capture=-1
        self.tracks={}
        self.cached=None

    def unknown_side(self, reason):
        return {'state':'unknown','reason':reason,'risk_observed':False,'control_eligible':False,
                'clearance_authorized':False,'coverage':'front_visible_only'}

    def reset(self, reason, stamp=None):
        self.tracks.clear()
        self.cached=self.output({s:self.unknown_side(reason) for s in ('left','right')},stamp)
        return self.cached

    def output(self, sides, stamp):
        return {'version':1,'mode':'observation_only','experimental':True,'capture_mono_ns':stamp,
                'control_eligible':False,'clearance_authorized':False,'rear_coverage_available':False,**sides}

    def update(self, packet, now_ns, *, related_lanes=()):
        c=self.config
        if not isinstance(packet,dict):return self.reset('malformed_packet')
        stamp=packet.get('updated_mono_ns');stream=packet.get('stream_id')
        if (type(packet.get('version')) is not int or packet['version']!=1 or
            packet.get('source')!='tesnav-phone' or packet.get('valid') is not True or
            packet.get('control_eligible') is not False or type(stamp) is not int or
            type(now_ns) is not int or not 0<=now_ns-stamp<=c.max_age_ns or
            not isinstance(stream,str) or not stream):
            return self.reset('invalid_or_stale_packet')
        if stamp<self.last_capture:return self.reset('out_of_order',stamp)
        if stream!=self.stream:
            if stamp<=self.last_capture:return self.reset('old_stream',stamp)
            self.tracks.clear();self.stream=stream
        elif stamp==self.last_capture and self.cached is not None:
            return self.cached
        if self.last_capture>=0 and stamp-self.last_capture>c.max_age_ns:self.tracks.clear()
        self.last_capture=stamp;sides={}
        for side in ('left','right'):
            v=packet.get(side);reason=None
            if not isinstance(v,dict):reason='no_confirmed_target'
            elif (type(v.get('track_id')) is not int or v['track_id']<0 or
                  type(v.get('hits')) is not int or v['hits']<5 or
                  not finite(v.get('confidence')) or not c.min_confidence<=v['confidence']<=1):reason='unconfirmed_target'
            elif not finite(v.get('distance_m')) or not 2<=v['distance_m']<=80:reason='unreliable_distance'
            if reason:
                self.tracks.pop(side,None);sides[side]=self.unknown_side(reason);continue
            track=self.tracks.get(side)
            if track is None or track['id']!=v['track_id']:
                track={'id':v['track_id'],'history':[],'risk_since':None};self.tracks[side]=track
            history=track['history']
            if history and abs(v['distance_m']-history[-1][1])>max(5.,30*(stamp-history[-1][0])/1e9):
                track['history']=[];track['risk_since']=None;sides[side]=self.unknown_side('distance_jump');continue
            history.append((stamp,float(v['distance_m'])));track['history']=[p for p in history if stamp-p[0]<=c.window_ns];history=track['history']
            if len(history)<c.min_samples or history[-1][0]-history[0][0]<c.min_span_ns:
                sides[side]=self.unknown_side('warming_up');continue
            xs=[(p[0]-history[0][0])/1e9 for p in history];ys=[p[1] for p in history];mx=sum(xs)/len(xs);my=sum(ys)/len(ys);den=sum((x-mx)**2 for x in xs)
            slope=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/den
            rmse=math.sqrt(sum((y-my-slope*(x-mx))**2 for x,y in zip(xs,ys))/len(xs))
            if rmse>c.max_fit_rmse_m or abs(slope)>c.max_relative_mps:
                track['risk_since']=None;sides[side]=self.unknown_side('unstable_range_fit');continue
            closing=max(0.,-slope);ttc=v['distance_m']/closing if closing>=c.min_closing_mps else None
            fast=ttc is not None and ttc<=c.max_gap_exhaustion_s
            if not fast:track['risk_since']=None
            elif track['risk_since'] is None:track['risk_since']=stamp
            confirmed=fast and stamp-track['risk_since']>=c.confirm_ns
            lane_related=side in related_lanes
            state=('closing_risk_observed' if lane_related else 'possible_closing_risk_lane_unknown') if confirmed else 'risk_confirmation_pending' if fast else 'no_fast_closing_observed'
            sides[side]={'state':state,'reason':'experimental_distance_trend','track_id':v['track_id'],
                         'distance_m':v['distance_m'],'relative_longitudinal_mps':slope,'closing_mps':closing,
                         'gap_exhaustion_estimate_s':ttc,'fit_rmse_m':rmse,'lane_related_confirmed':lane_related,
                         'risk_observed':confirmed,'control_eligible':False,'clearance_authorized':False,
                         'coverage':'front_visible_only'}
        self.cached=self.output(sides,stamp);return self.cached
