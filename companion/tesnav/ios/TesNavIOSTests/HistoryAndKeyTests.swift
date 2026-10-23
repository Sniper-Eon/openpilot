import XCTest
@testable import TesNavIOS

final class HistoryAndKeyTests: XCTestCase {
  func testHistorySurvivesStoreRecreationAndDeduplicates() {
    let suite = "tesnav-history-test.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let history = SearchHistoryStore(defaults: defaults)
    history.record(query: " 上海 ")
    history.record(query: "苏州")
    history.record(query: "上海")
    XCTAssertEqual(SearchHistoryStore(defaults: defaults).entries().map(\.query), ["上海", "苏州"])
    let place = Destination(name: "地点", address: "地址", poiID: "poi-1", latitude: 31.2, longitude: 121.4)
    history.record(destination: place)
    XCTAssertEqual(history.entries().first?.destination, place)
    history.remove(history.entries()[0])
    XCTAssertEqual(history.entries().count, 2)
    for index in 0..<25 { history.record(query: "地点\(index)") }
    XCTAssertEqual(history.entries().count, 20)
    history.clear()
    XCTAssertTrue(SearchHistoryStore(defaults: defaults).entries().isEmpty)
  }

  func testKeySetupPolicyAndSavedOverride() {
    for value in [nil, "", "   ", "$(AMAP_IOS_API_KEY)", "YOUR_API_KEY"] as [String?] {
      XCTAssertNil(AMapKeyPolicy.resolve(saved: nil, bundled: value))
    }
    let bundled = String(repeating: "a", count: 32)
    let saved = String(repeating: "b", count: 32)
    XCTAssertEqual(AMapKeyPolicy.resolve(saved: " \(saved)\n", bundled: bundled), saved)
    XCTAssertEqual(AMapKeyPolicy.resolve(saved: nil, bundled: bundled), bundled)
    XCTAssertNil(AMapKeyPolicy.resolve(saved: "invalid", bundled: bundled))
  }
}
