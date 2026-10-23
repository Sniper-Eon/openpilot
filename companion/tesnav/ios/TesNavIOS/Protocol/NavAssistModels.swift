import CryptoKit
import Foundation

enum NavAssistProtocol {
  static let schemaVersion = 3
  static let endpointPath = "/v3/snapshot"
  static let snapshotPort: UInt16 = 7766
  static let discoveryPort: UInt16 = 7765
  static let udpSnapshotPort: UInt16 = 4213
  static let validForMs: UInt64 = 1_200
}

struct NavAssistLocation: Encodable {
  let accuracyM: Double
  let bearingDeg: Double
  let currentLinkIndex: Int?
  let currentPointIndex: Int?
  let currentStepIndex: Int?
  let latitude: Double
  let longitude: Double
  let observedAtMs: UInt64
  let speedKph: Double
}

struct NavAssistGuidance: Encodable {
  let advisorySpeedMps: Double?
  let currentRoad: String?
  let maneuver: String
  let maneuverDistanceM: Int?
  let nextManeuver: String?
  let nextManeuverDistanceM: Int?
  let nextRoad: String?
  let observedAtMs: UInt64
  let roadClass: Int?
  let roadType: Int?
}

struct NavAssistLanes: Encodable {
  let items: [LaneObservation]
  let observedAtMs: UInt64
}

struct NavAssistSnapshot: Encodable {
  let coordinateSystem: String
  let gpsWeak: Bool
  let guidance: NavAssistGuidance?
  let lanes: NavAssistLanes?
  let location: NavAssistLocation?
  let maneuverEventId: UInt64
  let messageType: String
  let navigationMode: String
  let routeActive: Bool
  let routeMatched: Bool?
  let routeRevision: UInt64
  let schemaVersion: Int
  let sequence: UInt64
  let sessionId: String
  let sourcePlatform: String
  let sourceWallTimeMs: UInt64
  let validForMs: UInt64
}

final class NavAssistSession {
  let sessionID = UUID().uuidString
  private let lock = NSLock()
  private var sequence: UInt64 = 0

  func nextSnapshot(from state: NavigationObservation, nowMs: UInt64) -> NavAssistSnapshot {
    lock.lock()
    sequence &+= 1
    let nextSequence = sequence
    lock.unlock()

    let location = makeLocation(state)
    let guidance = makeGuidance(state)
    let sourceFresh = location != nil && guidance != nil
    let active = state.mode == "realtime" && state.routeActive && state.routeMatched == true && sourceFresh
    let eventKey = active && state.maneuver != "none" && state.maneuver != "unknown"
      ? "\(sessionID):\(state.routeRevision):\(state.currentStepIndex ?? -1):\(state.maneuver)"
      : nil

    return NavAssistSnapshot(
      coordinateSystem: "gcj02",
      gpsWeak: state.gpsWeak,
      guidance: guidance,
      lanes: state.laneObservedAtMs.map { NavAssistLanes(items: Array(state.lanes.prefix(16)), observedAtMs: $0) },
      location: location,
      maneuverEventId: eventKey.map(StableEventID.make) ?? 0,
      messageType: "navigation_snapshot",
      navigationMode: state.routeRecalculating ? "recalculating" : (state.arrived ? "arrived" : state.mode),
      routeActive: active,
      routeMatched: location == nil ? nil : state.routeMatched,
      routeRevision: state.routeRevision,
      schemaVersion: NavAssistProtocol.schemaVersion,
      sequence: nextSequence,
      sessionId: sessionID,
      sourcePlatform: "ios",
      sourceWallTimeMs: nowMs,
      validForMs: NavAssistProtocol.validForMs
    )
  }

  private func makeLocation(_ state: NavigationObservation) -> NavAssistLocation? {
    guard let latitude = state.latitude, (-90...90).contains(latitude),
          let longitude = state.longitude, (-180...180).contains(longitude),
          let accuracy = state.accuracyM, accuracy.isFinite, (0...200).contains(accuracy),
          let bearing = state.bearingDeg, bearing.isFinite, (0...360).contains(bearing),
          let speed = state.speedKph, speed.isFinite, (0...300).contains(speed),
          let observed = state.locationObservedAtMs else { return nil }
    return NavAssistLocation(
      accuracyM: accuracy,
      bearingDeg: bearing,
      currentLinkIndex: nonNegative(state.currentLinkIndex),
      currentPointIndex: nonNegative(state.currentPointIndex),
      currentStepIndex: nonNegative(state.currentStepIndex),
      latitude: latitude,
      longitude: longitude,
      observedAtMs: observed,
      speedKph: speed
    )
  }

  private func makeGuidance(_ state: NavigationObservation) -> NavAssistGuidance? {
    guard let observed = state.guidanceObservedAtMs else { return nil }
    return NavAssistGuidance(
      advisorySpeedMps: nil,
      currentRoad: boundedRoadName(state.currentRoad),
      maneuver: state.maneuver,
      maneuverDistanceM: state.maneuverDistanceM.flatMap { (0...100_000).contains($0) ? $0 : nil },
      nextManeuver: nil,
      nextManeuverDistanceM: nil,
      nextRoad: boundedRoadName(state.nextRoad),
      observedAtMs: observed,
      roadClass: state.roadClass,
      roadType: state.roadType
    )
  }

  private func nonNegative(_ value: Int?) -> Int? { value.flatMap { $0 >= 0 ? $0 : nil } }
  private func boundedRoadName(_ value: String?) -> String? {
    value.flatMap { !$0.isEmpty && $0.count <= 256 ? $0 : nil }
  }
}

enum StableEventID {
  static func make(_ key: String) -> UInt64 {
    let digest = SHA256.hash(data: Data(key.utf8))
    var value: UInt64 = 0
    for byte in digest.prefix(8) { value = (value << 8) | UInt64(byte) }
    value &= UInt64(Int64.max)
    return value == 0 ? 1 : value
  }
}

enum CanonicalJSON {
  static func encode<T: Encodable>(_ value: T) throws -> Data {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
    return try encoder.encode(value)
  }
}
