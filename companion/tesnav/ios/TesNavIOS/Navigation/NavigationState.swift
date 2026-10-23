import Foundation

struct Destination: Equatable, Codable {
  let name: String
  let address: String
  let poiID: String?
  let latitude: Double
  let longitude: Double
}

struct LaneObservation: Equatable, Codable {
  let index: Int
  let allowedActions: [String]
  let recommended: Bool
  let recommendedActions: [String]
}

struct NavigationObservation {
  var mode = "idle"
  var routeActive = false
  var routeMatched: Bool?
  var gpsWeak = true
  var latitude: Double?
  var longitude: Double?
  var accuracyM: Double?
  var bearingDeg: Double?
  var speedKph: Double?
  var locationObservedAtMs: UInt64?
  var guidanceObservedAtMs: UInt64?
  var laneObservedAtMs: UInt64?
  var currentStepIndex: Int?
  var currentLinkIndex: Int?
  var currentPointIndex: Int?
  var maneuver = "none"
  var maneuverDistanceM: Int?
  var currentRoad: String?
  var nextRoad: String?
  var roadClass: Int?
  var roadType: Int?
  var lanes: [LaneObservation] = []
  var routeRevision: UInt64 = 0
  var routeRecalculating = false
  var arrived = false
}

final class NavigationStateStore {
  static let shared = NavigationStateStore()

  private let lock = NSLock()
  private var observation = NavigationObservation()

  private init() {}

  func read() -> NavigationObservation {
    lock.lock()
    defer { lock.unlock() }
    return observation
  }

  func update(_ mutation: (inout NavigationObservation) -> Void) {
    lock.lock()
    mutation(&observation)
    lock.unlock()
  }

  func routeCalculated() {
    update {
      $0.routeRevision &+= 1
      if $0.mode != "realtime" && $0.mode != "simulation" {
        $0.mode = "route_planned"
      }
      $0.routeActive = false
      $0.routeMatched = nil
      $0.routeRecalculating = false
      $0.arrived = false
      $0.guidanceObservedAtMs = nil
      $0.laneObservedAtMs = nil
      $0.currentStepIndex = nil
      $0.currentLinkIndex = nil
      $0.currentPointIndex = nil
      $0.maneuver = "none"
      $0.maneuverDistanceM = nil
      $0.currentRoad = nil
      $0.nextRoad = nil
      $0.roadClass = nil
      $0.roadType = nil
      $0.lanes = []
    }
  }

  func startRealtime() {
    update {
      $0.mode = "realtime"
      $0.routeActive = false
      $0.arrived = false
    }
  }

  func startSimulation() {
    update {
      $0.mode = "simulation"
      $0.routeActive = false
      $0.arrived = false
    }
  }

  func navigationStartFailed() {
    update {
      $0.mode = "route_planned"
      $0.routeActive = false
    }
  }

  func stop() {
    update { $0 = NavigationObservation(routeRevision: $0.routeRevision) }
  }
}

extension NavigationObservation {
  init(routeRevision: UInt64) {
    self.init()
    self.routeRevision = routeRevision
  }
}
