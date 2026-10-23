import CryptoKit
import Foundation
import Security

enum NavAssistIdentityError: Error {
  case invalidKey
  case keychain(OSStatus)
}

final class NavAssistIdentity {
  #if targetEnvironment(simulator)
  static let shared = NavAssistIdentity(privateKey: P256.Signing.PrivateKey())
  #else
  static let shared = try! NavAssistIdentity()
  #endif

  let keyID: String
  let publicKeyText: String
  private let privateKey: P256.Signing.PrivateKey

  private init(privateKey: P256.Signing.PrivateKey) {
    self.privateKey = privateKey
    let der = privateKey.publicKey.derRepresentation
    publicKeyText = der.base64URLEncodedString()
    keyID = SHA256.hash(data: der).prefix(16).map { String(format: "%02x", $0) }.joined()
  }

  convenience init(keychain: NavAssistKeychain = .live) throws {
    let privateKey: P256.Signing.PrivateKey
    if let stored = try keychain.load() {
      privateKey = try P256.Signing.PrivateKey(rawRepresentation: stored)
    } else {
      let generated = P256.Signing.PrivateKey()
      try keychain.save(generated.rawRepresentation)
      privateKey = generated
    }
    guard privateKey.publicKey.derRepresentation.count == 91 else { throw NavAssistIdentityError.invalidKey }
    self.init(privateKey: privateKey)
  }

  func sign(_ data: Data) throws -> String {
    try privateKey.signature(for: data).derRepresentation.base64URLEncodedString()
  }

  static func verify(publicKeyText: String, data: Data, signatureText: String) -> Bool {
    guard let keyData = Data(base64URL: publicKeyText), keyData.count == 91,
          let signatureData = Data(base64URL: signatureText), signatureData.count <= 72,
          let key = try? P256.Signing.PublicKey(derRepresentation: keyData),
          let signature = try? P256.Signing.ECDSASignature(derRepresentation: signatureData)
    else { return false }
    return key.isValidSignature(signature, for: data)
  }

  static func keyID(for publicKeyText: String) -> String? {
    guard let data = Data(base64URL: publicKeyText), data.count == 91 else { return nil }
    return SHA256.hash(data: data).prefix(16).map { String(format: "%02x", $0) }.joined()
  }
}

struct NavAssistKeychain {
  static let live = NavAssistKeychain(service: "com.garan.tesnav.ios.navassist", account: "p256-signing-v3")

  let service: String
  let account: String

  func load() throws -> Data? {
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
      kSecReturnData as String: true,
      kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess, let data = item as? Data else {
      throw NavAssistIdentityError.keychain(status)
    }
    return data
  }

  func save(_ data: Data) throws {
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: account,
      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
      kSecValueData as String: data,
    ]
    let status = SecItemAdd(query as CFDictionary, nil)
    guard status == errSecSuccess || status == errSecDuplicateItem else {
      throw NavAssistIdentityError.keychain(status)
    }
  }
}

struct PinnedNavAssistDevice: Codable, Equatable {
  let deviceID: String
  let publicKey: String
}

final class NavAssistPairingStore {
  private let defaults: UserDefaults
  private let key = "navassist.paired-device.v3"

  init(defaults: UserDefaults = .standard) { self.defaults = defaults }

  func load() -> PinnedNavAssistDevice? {
    guard let data = defaults.data(forKey: key),
          let device = try? JSONDecoder().decode(PinnedNavAssistDevice.self, from: data),
          NavAssistIdentity.keyID(for: device.publicKey) == device.deviceID else { return nil }
    return device
  }

  @discardableResult
  func pin(_ device: PinnedNavAssistDevice) -> Bool {
    guard NavAssistIdentity.keyID(for: device.publicKey) == device.deviceID else { return false }
    if let existing = load(), existing != device { return false }
    guard let data = try? JSONEncoder().encode(device) else { return false }
    defaults.set(data, forKey: key)
    return true
  }

  func clear() { defaults.removeObject(forKey: key) }
}

extension Data {
  init?(base64URL: String) {
    var value = base64URL.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
    value += String(repeating: "=", count: (4 - value.count % 4) % 4)
    self.init(base64Encoded: value)
  }

  func base64URLEncodedString() -> String {
    base64EncodedString()
      .replacingOccurrences(of: "+", with: "-")
      .replacingOccurrences(of: "/", with: "_")
      .replacingOccurrences(of: "=", with: "")
  }
}
