import Foundation

final class NavigationTelemetry: NSObject, AMapNaviDriveDataRepresentable, AMapNaviDriveManagerDelegate {
  private let store = NavigationStateStore.shared
  private weak var manager: AMapNaviDriveManager?

  init(manager: AMapNaviDriveManager) {
    self.manager = manager
    super.init()
    manager.addDataRepresentative(self)
    manager.addEventListener(self)
  }

  deinit {
    manager?.removeDataRepresentative(self)
    manager?.removeEventListener(self)
  }

  func driveManager(_ driveManager: AMapNaviDriveManager, update naviMode: AMapNaviMode) {
    store.update {
      switch naviMode {
      case .GPS:
        $0.mode = "realtime"
      case .emulator:
        $0.mode = "simulation"
      default:
        $0.mode = $0.arrived ? "arrived" : "route_planned"
        $0.routeActive = false
      }
    }
  }

  func driveManager(_ driveManager: AMapNaviDriveManager, update naviLocation: AMapNaviLocation?) {
    guard let location = naviLocation, let point = location.coordinate else { return }
    let observedMs = NavigationObservationClock.milliseconds()
    store.update {
      $0.latitude = Double(point.latitude)
      $0.longitude = Double(point.longitude)
      $0.accuracyM = location.accuracy
      $0.bearingDeg = normalizedHeading(location.heading)
      $0.speedKph = Double(location.speed)
      $0.locationObservedAtMs = observedMs
      $0.currentStepIndex = Int(location.currentSegmentIndex)
      $0.currentLinkIndex = Int(location.currentLinkIndex)
      $0.currentPointIndex = Int(location.currentPointIndex)
      $0.routeMatched = location.isMatchNaviPath
      $0.routeActive = $0.mode == "realtime" && location.isMatchNaviPath
    }
  }

  func driveManager(_ driveManager: AMapNaviDriveManager, update naviInfo: AMapNaviInfo?) {
    guard let info = naviInfo else { return }
    let nowMs = NavigationObservationClock.milliseconds()
    let segmentIndex = info.currentSegmentIndex
    let linkIndex = info.currentLinkIndex
    let link = routeLink(manager: driveManager, segment: segmentIndex, link: linkIndex)
    let nextLink = routeLink(manager: driveManager, segment: segmentIndex + 1, link: 0)
    let maneuver = AMapManeuverMapper.wireValue(icon: info.iconType, formWay: nextLink?.formWay ?? link?.formWay)
    store.update {
      $0.guidanceObservedAtMs = nowMs
      $0.currentStepIndex = segmentIndex
      $0.currentLinkIndex = linkIndex
      $0.currentPointIndex = info.currentPointIndex
      $0.currentRoad = info.currentRoadName
      $0.nextRoad = info.nextRoadName
      $0.maneuver = maneuver
      $0.maneuverDistanceM = info.segmentRemainDistance
      $0.roadClass = link.map { Int($0.roadClass.rawValue) }
      $0.roadType = link.map { Int($0.formWay.rawValue) }
      $0.routeActive = $0.mode == "realtime" && $0.routeMatched == true
    }
  }

  func driveManager(
    _ driveManager: AMapNaviDriveManager,
    showLaneBackInfo laneBackInfo: String,
    laneSelectInfo: String
  ) {
    let back = parseLaneValues(laneBackInfo)
    let selected = parseLaneValues(laneSelectInfo)
    guard !back.isEmpty, back.count == selected.count else { return }
    let nowMs = NavigationObservationClock.milliseconds()
    store.update {
      $0.laneObservedAtMs = nowMs
      $0.lanes = zip(back, selected).enumerated().map { index, pair in
        let recommended = AMapLaneActionMapper.isRecommended(pair.1)
        return LaneObservation(
          index: index,
          allowedActions: AMapLaneActionMapper.actions(pair.0),
          recommended: recommended,
          recommendedActions: recommended ? AMapLaneActionMapper.actions(pair.1) : []
        )
      }
    }
  }

  func driveManagerHideLaneInfo(_ driveManager: AMapNaviDriveManager) {
    store.update {
      $0.laneObservedAtMs = NavigationObservationClock.milliseconds()
      $0.lanes = []
    }
  }

  func driveManager(_ driveManager: AMapNaviDriveManager, update gpsSignalStrength: AMapNaviGPSSignalStrength) {
    store.update { $0.gpsWeak = gpsSignalStrength == .weak || gpsSignalStrength == .unknow }
  }

  func driveManager(onArrivedDestination driveManager: AMapNaviDriveManager) {
    store.update {
      $0.arrived = true
      $0.mode = "arrived"
      $0.routeActive = false
    }
  }

  private func routeLink(manager: AMapNaviDriveManager, segment: Int, link: Int) -> AMapNaviLink? {
    guard let segments = manager.naviRoute?.routeSegments,
          segments.indices.contains(segment),
          segments[segment].links.indices.contains(link) else { return nil }
    return segments[segment].links[link]
  }

  private func normalizedHeading(_ heading: Double) -> Double {
    guard heading.isFinite else { return 0 }
    let value = heading.truncatingRemainder(dividingBy: 360)
    return value < 0 ? value + 360 : value
  }

  private func parseLaneValues(_ text: String?) -> [Int] {
    text?.split(separator: "|").compactMap { Int($0) } ?? []
  }

}

enum NavigationObservationClock {
  static func milliseconds(_ date: Date = Date()) -> UInt64 {
    UInt64(max(0, date.timeIntervalSince1970 * 1_000))
  }
}

enum AMapManeuverMapper {
  static func wireValue(icon: AMapNaviIconType, formWay: AMapNaviFormWay?) -> String {
    let direction: String
    switch icon {
    case .left: direction = "turn_left"
    case .right: direction = "turn_right"
    case .leftFront: direction = "slight_left"
    case .rightFront: direction = "slight_right"
    case .leftBack: direction = "sharp_left"
    case .rightBack: direction = "sharp_right"
    case .leftAndAround: direction = "u_turn_left"
    case .uTurnRight: direction = "u_turn_right"
    case .straight, .specialContinue: direction = "straight"
    case .mergeLeft: direction = "merge_left"
    case .mergeRight: direction = "merge_right"
    case .enterRoundabout, .outRoundabout, .entryRingLeft, .entryRingRight, .entryRingContinue, .entryRingUTurn,
         .entryLeftRingLeft, .entryLeftRingRight, .entryLeftRingContinue, .entryLeftRingUTurn:
      direction = "roundabout"
    case .arrivedDestination: direction = "destination"
    default: direction = "unknown"
    }

    if formWay == .exit {
      if direction.contains("left") { return "exit_left" }
      if direction.contains("right") { return "exit_right" }
    }
    if formWay == .ramp || formWay == .rampAndJCT {
      if direction.contains("left") { return "ramp_left" }
      if direction.contains("right") { return "ramp_right" }
    }
    return direction
  }
}

enum AMapLaneActionMapper {
  static func isRecommended(_ value: Int) -> Bool { !actions(value).isEmpty }

  static func actions(_ value: Int) -> [String] {
    switch value {
    case 0: ["STRAIGHT"]
    case 1: ["LEFT"]
    case 2: ["STRAIGHT", "LEFT"]
    case 3: ["RIGHT"]
    case 4: ["STRAIGHT", "RIGHT"]
    case 5: ["LEFT_U_TURN"]
    case 6: ["LEFT", "RIGHT"]
    case 7: ["STRAIGHT", "LEFT", "RIGHT"]
    case 8: ["RIGHT_U_TURN"]
    case 9: ["STRAIGHT", "LEFT_U_TURN"]
    case 10: ["STRAIGHT", "RIGHT_U_TURN"]
    case 11, 14: ["LEFT", "LEFT_U_TURN"]
    case 12: ["RIGHT", "RIGHT_U_TURN"]
    case 13: ["STRAIGHT"]
    case 16: ["STRAIGHT", "LEFT", "LEFT_U_TURN"]
    case 17: ["RIGHT", "LEFT_U_TURN"]
    case 18: ["LEFT", "RIGHT", "LEFT_U_TURN"]
    case 19: ["STRAIGHT", "RIGHT", "LEFT_U_TURN"]
    case 20: ["LEFT", "RIGHT_U_TURN"]
    case 21: ["BUS"]
    case 23: ["VARIABLE"]
    case 24: ["DEDICATED"]
    case 25: ["TIDAL"]
    case 15, 22, 255: []
    default: ["UNKNOWN"]
    }
  }

}
