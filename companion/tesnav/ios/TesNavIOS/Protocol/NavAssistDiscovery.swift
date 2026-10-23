import Darwin
import Foundation

struct NavAssistEndpoint: Equatable {
  let host: String
  let deviceID: String

  var url: URL { URL(string: "http://\(host):\(NavAssistProtocol.snapshotPort)\(NavAssistProtocol.endpointPath)")! }
}

enum NavAssistDiscoveryError: LocalizedError {
  case socket
  case noDevice
  case multipleDevices
  case pairingConflict

  var errorDescription: String? {
    switch self {
    case .socket: "局域网扫描失败"
    case .noDevice: "未发现 C3XL"
    case .multipleDevices: "发现多个已认证 C3XL"
    case .pairingConflict: "C3XL 配对身份冲突"
    }
  }
}

final class NavAssistDiscovery {
  private let identity: NavAssistIdentity
  private let pairingStore: NavAssistPairingStore

  init(identity: NavAssistIdentity, pairingStore: NavAssistPairingStore = NavAssistPairingStore()) {
    self.identity = identity
    self.pairingStore = pairingStore
  }

  func clearPairing() { pairingStore.clear() }

  func hasPairing() -> Bool { pairingStore.load() != nil }

  func discover() throws -> NavAssistEndpoint {
    let nonce = randomNonce()
    let requestMaterial = "navassist_discovery_request\n3\n\(nonce)\n\(identity.keyID)\n\(identity.publicKeyText)"
    let signature = try identity.sign(Data(requestMaterial.utf8))
    let requestObject: [String: Any] = [
      "messageType": "navassist_discovery_request",
      "schemaVersion": 3,
      "nonce": nonce,
      "appKeyId": identity.keyID,
      "appPublicKey": identity.publicKeyText,
      "signature": signature,
    ]
    let request = try JSONSerialization.data(withJSONObject: requestObject, options: [.sortedKeys, .withoutEscapingSlashes])
    guard request.count <= 512 else { throw NavAssistDiscoveryError.socket }

    let offers = try UdpBroadcast.exchange(request).compactMap {
      authenticatedOffer(payload: $0.payload, sourceHost: $0.sourceHost, nonce: nonce)
    }
    let pinned = pairingStore.load()
    let candidates = offers.filter { offer in
      pinned == nil || pinned == PinnedNavAssistDevice(deviceID: offer.deviceID, publicKey: offer.publicKey)
    }.reduce(into: [String: AuthenticatedOffer]()) { result, offer in
      result["\(offer.deviceID)@\(offer.host)"] = offer
    }.values

    guard !candidates.isEmpty else { throw NavAssistDiscoveryError.noDevice }
    guard candidates.count == 1, let candidate = candidates.first else { throw NavAssistDiscoveryError.multipleDevices }
    guard pairingStore.pin(PinnedNavAssistDevice(deviceID: candidate.deviceID, publicKey: candidate.publicKey)) else {
      throw NavAssistDiscoveryError.pairingConflict
    }
    return NavAssistEndpoint(host: candidate.host, deviceID: candidate.deviceID)
  }

  private func authenticatedOffer(payload: Data, sourceHost: String, nonce: String) -> AuthenticatedOffer? {
    guard payload.count <= 512, isPrivateIPv4(sourceHost), let fields = StrictFlatJSON.parse(payload) else { return nil }
    let expectedKeys: Set<String> = [
      "messageType", "schemaVersion", "nonce", "appKeyId", "deviceId", "devicePublicKey", "port", "path", "signature",
    ]
    guard Set(fields.keys) == expectedKeys,
          fields.string("messageType") == "navassist_discovery_offer",
          fields.integer("schemaVersion") == 3,
          fields.string("nonce") == nonce,
          fields.string("appKeyId") == identity.keyID,
          fields.integer("port") == Int(NavAssistProtocol.snapshotPort),
          fields.string("path") == NavAssistProtocol.endpointPath,
          let deviceID = fields.string("deviceId"), deviceID.matches("^[0-9a-f]{32}$"),
          let publicKey = fields.string("devicePublicKey"), NavAssistIdentity.keyID(for: publicKey) == deviceID,
          let signature = fields.string("signature") else { return nil }
    let material = "navassist_discovery_offer\n3\n\(nonce)\n\(identity.keyID)\n\(deviceID)\n\(publicKey)\n7766\n/v3/snapshot"
    guard NavAssistIdentity.verify(publicKeyText: publicKey, data: Data(material.utf8), signatureText: signature) else { return nil }
    return AuthenticatedOffer(host: sourceHost, deviceID: deviceID, publicKey: publicKey)
  }

  private func randomNonce() -> String {
    var bytes = [UInt8](repeating: 0, count: 16)
    _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
    return bytes.map { String(format: "%02x", $0) }.joined()
  }

  private func isPrivateIPv4(_ host: String) -> Bool {
    let parts = host.split(separator: ".").compactMap { UInt8($0) }
    guard parts.count == 4 else { return false }
    return parts[0] == 10 || (parts[0] == 172 && (16...31).contains(parts[1])) || (parts[0] == 192 && parts[1] == 168)
  }
}

private struct AuthenticatedOffer {
  let host: String
  let deviceID: String
  let publicKey: String
}

struct UdpDatagram {
  let sourceHost: String
  let payload: Data
}

enum IPv4DirectedBroadcast {
  static func address(ip: UInt32, netmask: UInt32) -> UInt32 {
    (ip & netmask) | ~netmask
  }
}

enum UdpBroadcast {
  static func exchange(
    _ request: Data,
    port: UInt16 = NavAssistProtocol.discoveryPort,
    receiveWindow: TimeInterval = 0.75,
    maxResponseBytes: Int = 512
  ) throws -> [UdpDatagram] {
    let descriptor = Darwin.socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
    guard descriptor >= 0 else { throw NavAssistDiscoveryError.socket }
    defer { Darwin.close(descriptor) }

    var enabled: Int32 = 1
    guard setsockopt(descriptor, SOL_SOCKET, SO_BROADCAST, &enabled, socklen_t(MemoryLayout.size(ofValue: enabled))) == 0 else {
      throw NavAssistDiscoveryError.socket
    }

    var successfulTargets = 0
    for address in broadcastTargets() {
      var target = sockaddr_in()
      target.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
      target.sin_family = sa_family_t(AF_INET)
      target.sin_port = port.bigEndian
      target.sin_addr = address
      let sent = request.withUnsafeBytes { bytes in
        withUnsafePointer(to: &target) { pointer in
          pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            sendto(descriptor, bytes.baseAddress, bytes.count, 0, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
          }
        }
      }
      if sent == request.count { successfulTargets += 1 }
    }
    guard successfulTargets > 0 else { throw NavAssistDiscoveryError.socket }

    let deadline = Date().addingTimeInterval(receiveWindow)
    var results: [UdpDatagram] = []
    while Date() < deadline && results.count < 64 {
      let remaining = max(1, Int32(deadline.timeIntervalSinceNow * 1_000))
      var pollDescriptor = pollfd(fd: descriptor, events: Int16(POLLIN), revents: 0)
      guard Darwin.poll(&pollDescriptor, 1, remaining) > 0 else { break }

      var source = sockaddr_in()
      var sourceLength = socklen_t(MemoryLayout<sockaddr_in>.size)
      var buffer = [UInt8](repeating: 0, count: maxResponseBytes + 1)
      let count = withUnsafeMutablePointer(to: &source) { pointer in
        pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
          recvfrom(descriptor, &buffer, buffer.count, 0, $0, &sourceLength)
        }
      }
      guard count > 0, count <= maxResponseBytes else { continue }
      var address = source.sin_addr
      var text = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
      guard inet_ntop(AF_INET, &address, &text, socklen_t(INET_ADDRSTRLEN)) != nil else { continue }
      results.append(UdpDatagram(sourceHost: String(cString: text), payload: Data(buffer.prefix(count))))
    }
    return results
  }

  private static func broadcastTargets() -> [in_addr] {
    var targets: [UInt32] = []
    var interfaces: UnsafeMutablePointer<ifaddrs>?
    if getifaddrs(&interfaces) == 0 {
      defer { freeifaddrs(interfaces) }
      var cursor = interfaces
      while let current = cursor {
        let interface = current.pointee
        cursor = interface.ifa_next
        let flags = interface.ifa_flags
        guard flags & UInt32(IFF_UP) != 0,
              flags & UInt32(IFF_BROADCAST) != 0,
              flags & UInt32(IFF_LOOPBACK) == 0,
              let addressPointer = interface.ifa_addr,
              let netmaskPointer = interface.ifa_netmask,
              addressPointer.pointee.sa_family == sa_family_t(AF_INET),
              netmaskPointer.pointee.sa_family == sa_family_t(AF_INET) else { continue }
        let address = addressPointer.withMemoryRebound(to: sockaddr_in.self, capacity: 1) {
          UInt32(bigEndian: $0.pointee.sin_addr.s_addr)
        }
        let netmask = netmaskPointer.withMemoryRebound(to: sockaddr_in.self, capacity: 1) {
          UInt32(bigEndian: $0.pointee.sin_addr.s_addr)
        }
        let broadcast = IPv4DirectedBroadcast.address(ip: address, netmask: netmask)
        if broadcast != address { targets.append(broadcast.bigEndian) }
      }
    }
    if targets.isEmpty { targets.append(INADDR_BROADCAST) }
    return Array(Set(targets)).map { in_addr(s_addr: $0) }
  }
}

enum UnauthenticatedNavAssistUDP {
  static let maxAckBytes = 2 * 1_024

  // A matching ACK confirms transport only; optional vehicle feedback is not displayed here.
  static func matchesAck(_ payload: Data, sessionID: String, sequence: UInt64) -> Bool {
    let required: Set<String> = ["messageType", "schemaVersion", "sessionId", "sequence"]
    guard !payload.isEmpty, payload.count <= maxAckBytes,
          sequence > 0, sequence <= UInt64(Int64.max),
          String(data: payload, encoding: .utf8) != nil,
          let object = try? JSONSerialization.jsonObject(with: payload) as? [String: Any],
          let fields = ackMembers(payload),
          required.isSubset(of: Set(object.keys)),
          Set(object.keys).isSubset(of: required.union(["vehicleLane"])),
          object["messageType"] as? String == "navassist_udp_ack",
          object["sessionId"] as? String == sessionID,
          fields["schemaVersion"] == String(NavAssistProtocol.schemaVersion),
          fields["sequence"] == String(sequence) else { return false }
    if let feedback = fields["vehicleLane"], feedback.first == "{",
       ackMembers(Data(feedback.utf8)) == nil { return false }
    return true
  }

  // Foundation validates JSON syntax. This bounded scan retains exact integer tokens and
  // detects duplicate decoded keys in the envelope and its one flat feedback object.
  private static func ackMembers(_ data: Data) -> [String: String]? {
    guard let text = String(data: data, encoding: .utf8) else { return nil }
    let bytes = Array(text.trimmingCharacters(in: .whitespacesAndNewlines).utf8)
    guard bytes.first == 0x7b, bytes.last == 0x7d else { return nil }
    var result: [String: String] = [:]
    var depth = 1
    var quoted = false
    var escaped = false
    var start = 1
    var colon: Int?
    var previous: UInt8 = 0x7b
    for index in 1..<bytes.count {
      let byte = bytes[index]
      if quoted {
        if escaped { escaped = false }
        else if byte == 0x5c { escaped = true }
        else if byte == 0x22 { quoted = false }
        previous = byte
        continue
      }
      if [0x20, 0x09, 0x0a, 0x0d].contains(byte) { continue }
      if byte == 0x22 { quoted = true; previous = byte; continue }
      if (byte == 0x7d || byte == 0x5d) && previous == 0x2c { return nil }
      if depth == 1 && (byte == 0x2c || byte == 0x7d) {
        if let separator = colon {
          let keyData = Data(bytes[start..<separator])
          guard let key = (try? JSONSerialization.jsonObject(with: keyData, options: [.fragmentsAllowed])) as? String,
                result[key] == nil else { return nil }
          let value = String(decoding: bytes[(separator + 1)..<index], as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
          guard !value.isEmpty else { return nil }
          result[key] = value
        } else if byte != 0x7d || previous != 0x7b { return nil }
        start = index + 1
        colon = nil
      } else if depth == 1 && byte == 0x3a {
        guard colon == nil else { return nil }
        colon = index
      }
      if byte == 0x7b || byte == 0x5b { depth += 1 }
      if byte == 0x7d || byte == 0x5d { depth -= 1 }
      previous = byte
    }
    return depth == 0 && !quoted ? result : nil
  }

  static func send(snapshot: Data, sessionID: String, sequence: UInt64) throws -> String? {
    guard !snapshot.isEmpty, snapshot.count <= 8 * 1_024 else { throw NavAssistDiscoveryError.socket }
    let responses = try UdpBroadcast.exchange(
      snapshot,
      port: NavAssistProtocol.udpSnapshotPort,
      receiveWindow: 0.35,
      maxResponseBytes: maxAckBytes
    )
    for response in responses {
      guard matchesAck(response.payload, sessionID: sessionID, sequence: sequence) else { continue }
      return response.sourceHost
    }
    return nil
  }
}

private enum FlatJSONValue {
  case string(String)
  case integer(Int)
}

private extension Dictionary where Key == String, Value == FlatJSONValue {
  func string(_ key: String) -> String? {
    guard case let .string(value) = self[key] else { return nil }
    return value
  }

  func integer(_ key: String) -> Int? {
    guard case let .integer(value) = self[key] else { return nil }
    return value
  }
}

private enum StrictFlatJSON {
  static func parse(_ data: Data) -> [String: FlatJSONValue]? {
    guard data.allSatisfy({ $0 >= 0x20 && $0 <= 0x7e }), let text = String(data: data, encoding: .utf8) else { return nil }
    var parser = Parser(bytes: Array(text.utf8))
    return parser.parse()
  }

  private struct Parser {
    let bytes: [UInt8]
    var index = 0

    mutating func parse() -> [String: FlatJSONValue]? {
      skipWhitespace()
      guard take(0x7b) else { return nil }
      var result: [String: FlatJSONValue] = [:]
      skipWhitespace()
      if take(0x7d) { return atEnd ? result : nil }
      while true {
        skipWhitespace()
        guard let key = quotedString(), result[key] == nil else { return nil }
        skipWhitespace()
        guard take(0x3a) else { return nil }
        skipWhitespace()
        guard let value = value() else { return nil }
        result[key] = value
        skipWhitespace()
        if take(0x7d) { return atEnd ? result : nil }
        guard take(0x2c) else { return nil }
      }
    }

    mutating func value() -> FlatJSONValue? {
      if current == 0x22 { return quotedString().map(FlatJSONValue.string) }
      let start = index
      if current == 0x2d { index += 1 }
      while let byte = current, byte >= 0x30, byte <= 0x39 { index += 1 }
      guard index > start, let number = Int(String(decoding: bytes[start..<index], as: UTF8.self)) else { return nil }
      return .integer(number)
    }

    mutating func quotedString() -> String? {
      guard take(0x22) else { return nil }
      let start = index
      while let byte = current, byte != 0x22 {
        guard byte >= 0x20, byte != 0x5c else { return nil }
        index += 1
      }
      guard current == 0x22 else { return nil }
      let value = String(decoding: bytes[start..<index], as: UTF8.self)
      index += 1
      return value
    }

    mutating func skipWhitespace() {
      while let byte = current, [0x20, 0x09, 0x0a, 0x0d].contains(byte) { index += 1 }
    }

    mutating func take(_ byte: UInt8) -> Bool {
      guard current == byte else { return false }
      index += 1
      return true
    }

    var current: UInt8? { index < bytes.count ? bytes[index] : nil }
    var atEnd: Bool {
      var copy = self
      copy.skipWhitespace()
      return copy.index == bytes.count
    }
  }
}

private extension String {
  func matches(_ pattern: String) -> Bool { range(of: pattern, options: .regularExpression) != nil }
}
