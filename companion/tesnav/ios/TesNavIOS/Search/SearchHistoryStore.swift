import Foundation

struct SearchHistoryEntry: Codable, Equatable {
  let query: String
  let destination: Destination?

  var identity: String {
    if let place = destination {
      return "place:\(place.poiID?.isEmpty == false ? place.poiID! : "\(place.latitude),\(place.longitude):\(place.name)")"
    }
    return "query:\(query.lowercased())"
  }

  var isValid: Bool {
    guard !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, query.count <= 256 else { return false }
    guard let place = destination else { return true }
    return place.latitude.isFinite && place.longitude.isFinite && (-90...90).contains(place.latitude) && (-180...180).contains(place.longitude)
  }
}

final class SearchHistoryStore {
  private let defaults: UserDefaults
  private let key = "tesnav.search-history.v1"

  init(defaults: UserDefaults = .standard) { self.defaults = defaults }

  func entries() -> [SearchHistoryEntry] {
    guard let data = defaults.data(forKey: key),
          let decoded = try? JSONDecoder().decode([SearchHistoryEntry].self, from: data) else { return [] }
    var seen = Set<String>()
    return Array(decoded.filter { $0.isValid && seen.insert($0.identity).inserted }.prefix(20))
  }

  func record(query: String) {
    record(SearchHistoryEntry(query: query.trimmingCharacters(in: .whitespacesAndNewlines), destination: nil))
  }

  func record(destination: Destination) {
    record(SearchHistoryEntry(query: destination.name.trimmingCharacters(in: .whitespacesAndNewlines), destination: destination))
  }

  private func record(_ entry: SearchHistoryEntry) {
    guard entry.isValid else { return }
    save(Array(([entry] + entries().filter { $0.identity != entry.identity }).prefix(20)))
  }

  func remove(_ entry: SearchHistoryEntry) { save(entries().filter { $0.identity != entry.identity }) }
  func clear() { defaults.removeObject(forKey: key) }
  private func save(_ entries: [SearchHistoryEntry]) {
    guard let data = try? JSONEncoder().encode(entries) else { return }
    defaults.set(data, forKey: key)
  }
}
