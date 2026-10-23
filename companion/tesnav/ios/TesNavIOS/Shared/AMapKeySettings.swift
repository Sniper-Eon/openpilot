import Foundation
import Security

enum AMapKeyPolicy {
  static func normalized(_ value: String?) -> String? {
    guard let key = value?.trimmingCharacters(in: .whitespacesAndNewlines),
          key.range(of: "^[a-fA-F0-9]{32}$", options: .regularExpression) != nil else { return nil }
    return key
  }

  static func resolve(saved: String?, bundled: String?) -> String? {
    normalized(saved ?? bundled)
  }
}

enum AMapKeySettings {
  private static let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "com.garan.tesnav.ios.amap",
    kSecAttrAccount as String: "sdk-key",
  ]

  static var current: String? {
    var lookup = query
    lookup[kSecReturnData as String] = true
    lookup[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(lookup as CFDictionary, &result)
    let saved = status == errSecSuccess ? (result as? Data).flatMap { String(data: $0, encoding: .utf8) } : nil
    return AMapKeyPolicy.resolve(saved: saved, bundled: Bundle.main.object(forInfoDictionaryKey: "AMapAPIKey") as? String)
  }

  static func save(_ raw: String) throws {
    guard let key = AMapKeyPolicy.normalized(raw) else { throw KeyError.invalid }
    let attributes = [kSecValueData as String: Data(key.utf8)]
    var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
      var item = query.merging(attributes) { _, new in new }
      item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
      status = SecItemAdd(item as CFDictionary, nil)
    }
    guard status == errSecSuccess else { throw KeyError.storage(status) }
  }

  enum KeyError: LocalizedError {
    case invalid
    case storage(OSStatus)
    var errorDescription: String? {
      switch self {
      case .invalid: return "请输入完整的 32 位高德 iOS Key。"
      case .storage: return "Key 保存失败，请解锁手机后重试。"
      }
    }
  }
}
