import Foundation

extension Notification.Name {
  static let navAssistStatusChanged = Notification.Name("NavAssistStatusChanged")
}

enum NavAssistGuidanceState {
  case inactive, ready, waiting, stale

  static func display(_ state: NavigationObservation, nowMs _: UInt64) -> (NavAssistGuidanceState, String) {
    if state.mode == "simulation" { return (.inactive, "模拟导航预览") }
    if state.arrived { return (.inactive, "已到达目的地") }
    if state.mode != "realtime" { return (.inactive, "选择目的地并开始导航") }
    if state.routeRecalculating { return (.waiting, "正在重新规划路线") }
    guard state.guidanceObservedAtMs != nil else { return (.waiting, "等待高德更新引导信息") }
    guard state.routeMatched == true, state.routeActive else { return (.waiting, "等待匹配当前路线") }
    guard let latitude = state.latitude, (-90...90).contains(latitude),
          let longitude = state.longitude, (-180...180).contains(longitude),
          let accuracy = state.accuracyM, (0...200).contains(accuracy),
          let bearing = state.bearingDeg, (0...360).contains(bearing),
          let speed = state.speedKph, (0...300).contains(speed),
          state.locationObservedAtMs != nil else { return (.waiting, "等待完整导航信息") }
    return (.ready, "路线已匹配 · 导航联动已启用")
  }
}

struct NavAssistClientStatus {
  enum Connection: String {
    case stopped
    case scanning
    case discovered
    case online
    case error
  }

  let connection: Connection
  let endpoint: String?
  let deviceID: String?
  let appKeyID: String
  let detail: String
  var guidanceState: NavAssistGuidanceState = .inactive
  var guidanceDetail: String = "尚未开始导航"
}

final class NavAssistClient {
  static let shared = NavAssistClient()

  private let queue = DispatchQueue(label: "com.garan.tesnav.navassist", qos: .utility)
  private let identity = NavAssistIdentity.shared
  private let session = NavAssistSession()
  private let stateStore = NavigationStateStore.shared
  private let discovery: NavAssistDiscovery
  private let lock = NSLock()
  private var running = false
  private var discoveryResetRequested = false
  private var currentStatus: NavAssistClientStatus

  private init() {
    discovery = NavAssistDiscovery(identity: identity)
    currentStatus = NavAssistClientStatus(
      connection: .stopped,
      endpoint: nil,
      deviceID: nil,
      appKeyID: identity.keyID,
      detail: "等待启动"
    )
  }

  func start() {
    lock.lock()
    guard !running else { lock.unlock(); return }
    running = true
    lock.unlock()
    queue.async { [weak self] in self?.runLoop() }
  }

  func stop() {
    lock.lock()
    running = false
    lock.unlock()
    publish(.stopped, endpoint: nil, deviceID: nil, detail: "已停止")
  }

  func status() -> NavAssistClientStatus {
    lock.lock()
    defer { lock.unlock() }
    return currentStatus
  }

  func clearPairing() {
    discovery.clearPairing()
    requestRediscovery(detail: "已忘记配对，正在重新扫描")
  }

  func requestRediscovery() {
    requestRediscovery(detail: "导航开始，正在重新发现当前 C3XL 地址")
  }

  private func requestRediscovery(detail: String) {
    lock.lock()
    discoveryResetRequested = true
    lock.unlock()
    publish(.scanning, endpoint: nil, deviceID: nil, detail: detail)
  }

  func hasPairing() -> Bool { discovery.hasPairing() }

  private func runLoop() {
    while isRunning {
      _ = consumeDiscoveryReset()
      let sendStartedAt = ProcessInfo.processInfo.systemUptime
      do {
        let nowMs = UInt64(Date().timeIntervalSince1970 * 1_000)
        let snapshot = session.nextSnapshot(from: stateStore.read(), nowMs: nowMs)
        let body = try CanonicalJSON.encode(snapshot)
        if let host = try UnauthenticatedNavAssistUDP.send(
          snapshot: body, sessionID: snapshot.sessionId, sequence: snapshot.sequence
        ) {
          publish(.online, endpoint: "udp://\(host):4213", deviceID: host, detail: "已连接 C3XL")
        } else {
          publish(.scanning, endpoint: nil, deviceID: nil, detail: "请保持手机和 C3XL 连接同一 Wi-Fi")
        }
      } catch {
        publish(.error, endpoint: nil, deviceID: nil, detail: "连接失败：\(error.localizedDescription)")
      }
      let elapsed = ProcessInfo.processInfo.systemUptime - sendStartedAt
      Thread.sleep(forTimeInterval: NavAssistPublishCadence.remainingDelay(after: elapsed))
    }
  }

  private func post(to endpoint: NavAssistEndpoint) throws {
    let nowMs = UInt64(Date().timeIntervalSince1970 * 1_000)
    let snapshot = session.nextSnapshot(from: stateStore.read(), nowMs: nowMs)
    let body = try CanonicalJSON.encode(snapshot)
    let prefix = "navassist_snapshot\n3\nPOST\n/v3/snapshot\n\(endpoint.deviceID)\n\(identity.keyID)\n\(body.count)\n"
    let signature = try identity.sign(Data(prefix.utf8) + body)
    var request = URLRequest(url: endpoint.url, timeoutInterval: 1.5)
    request.httpMethod = "POST"
    request.httpBody = body
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue(identity.keyID, forHTTPHeaderField: "X-NavAssist-Key-Id")
    request.setValue(signature, forHTTPHeaderField: "X-NavAssist-Signature")

    let semaphore = DispatchSemaphore(value: 0)
    var result: Result<Void, Error> = .failure(URLError(.unknown))
    URLSession.shared.dataTask(with: request) { _, response, error in
      if let error {
        result = .failure(error)
      } else if let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) {
        result = .success(())
      } else {
        result = .failure(URLError(.badServerResponse))
      }
      semaphore.signal()
    }.resume()
    if semaphore.wait(timeout: .now() + 2) == .timedOut { throw URLError(.timedOut) }
    try result.get()
  }

  private var isRunning: Bool {
    lock.lock()
    defer { lock.unlock() }
    return running
  }

  private func consumeDiscoveryReset() -> Bool {
    lock.lock()
    defer { lock.unlock() }
    let requested = discoveryResetRequested
    discoveryResetRequested = false
    return requested
  }

  private func publish(
    _ connection: NavAssistClientStatus.Connection,
    endpoint: String?,
    deviceID: String?,
    detail: String
  ) {
    let guidance = NavAssistGuidanceState.display(stateStore.read(), nowMs: UInt64(Date().timeIntervalSince1970 * 1_000))
    let status = NavAssistClientStatus(
      connection: connection,
      endpoint: endpoint,
      deviceID: deviceID,
      appKeyID: identity.keyID,
      detail: detail,
      guidanceState: guidance.0,
      guidanceDetail: guidance.1
    )
    lock.lock()
    currentStatus = status
    lock.unlock()
    DispatchQueue.main.async {
      NotificationCenter.default.post(name: .navAssistStatusChanged, object: status)
    }
  }
}

enum NavAssistPublishCadence {
  static let interval: TimeInterval = 0.2

  static func remainingDelay(after elapsed: TimeInterval) -> TimeInterval {
    max(0, interval - max(0, elapsed))
  }
}
