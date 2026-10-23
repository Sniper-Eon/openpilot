import UIKit

final class ConnectionStatusView: UIView {
  private let symbolView = UIImageView()
  private let titleLabel = UILabel()
  private let detailLabel = UILabel()
  private var statusObserver: NSObjectProtocol?

  init(compact: Bool = false) {
    super.init(frame: .zero)
    backgroundColor = .secondarySystemGroupedBackground
    layer.cornerRadius = compact ? 14 : 18
    layer.borderWidth = 1
    layer.borderColor = UIColor.separator.withAlphaComponent(0.25).cgColor
    accessibilityIdentifier = "navAssistConnectionCard"

    symbolView.translatesAutoresizingMaskIntoConstraints = false
    symbolView.contentMode = .scaleAspectFit
    symbolView.preferredSymbolConfiguration = UIImage.SymbolConfiguration(pointSize: compact ? 20 : 24, weight: .semibold)
    symbolView.setContentHuggingPriority(.required, for: .horizontal)
    titleLabel.font = .preferredFont(forTextStyle: .headline)
    titleLabel.adjustsFontForContentSizeCategory = true
    titleLabel.textColor = .label
    titleLabel.numberOfLines = 2
    detailLabel.font = .preferredFont(forTextStyle: .subheadline)
    detailLabel.adjustsFontForContentSizeCategory = true
    detailLabel.textColor = .secondaryLabel
    detailLabel.numberOfLines = compact ? 2 : 3

    let text = UIStackView(arrangedSubviews: [titleLabel, detailLabel])
    text.axis = .vertical
    text.spacing = 4
    let row = UIStackView(arrangedSubviews: [symbolView, text])
    row.translatesAutoresizingMaskIntoConstraints = false
    row.axis = .horizontal
    row.alignment = .center
    row.spacing = 12
    addSubview(row)
    let inset: CGFloat = compact ? 12 : 16
    NSLayoutConstraint.activate([
      row.topAnchor.constraint(equalTo: topAnchor, constant: inset),
      row.leadingAnchor.constraint(equalTo: leadingAnchor, constant: inset),
      row.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -inset),
      row.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -inset),
      symbolView.widthAnchor.constraint(equalToConstant: compact ? 26 : 32),
      symbolView.heightAnchor.constraint(equalToConstant: compact ? 26 : 32),
    ])
    isAccessibilityElement = true
    update(NavAssistClient.shared.status())
    statusObserver = NotificationCenter.default.addObserver(forName: .navAssistStatusChanged, object: nil, queue: .main) {
      [weak self] notification in
      guard let status = notification.object as? NavAssistClientStatus else { return }
      self?.update(status)
    }
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  deinit {
    if let statusObserver { NotificationCenter.default.removeObserver(statusObserver) }
  }

  override func traitCollectionDidChange(_ previousTraitCollection: UITraitCollection?) {
    super.traitCollectionDidChange(previousTraitCollection)
    layer.borderColor = UIColor.separator.withAlphaComponent(0.25).cgColor
  }

  private func update(_ status: NavAssistClientStatus) {
    switch status.connection {
    case .online:
      detailLabel.text = status.guidanceDetail
      switch status.guidanceState {
      case .ready:
        titleLabel.text = "C3XL 已连接 · 导航信息有效"
        symbolView.image = UIImage(systemName: "checkmark.circle.fill")
        symbolView.tintColor = .systemGreen
      case .inactive:
        titleLabel.text = "C3XL 已连接 · 暂无实时导航"
        symbolView.image = UIImage(systemName: "car.fill")
        symbolView.tintColor = .systemBlue
      case .waiting:
        titleLabel.text = "C3XL 已连接 · 等待导航信息"
        symbolView.image = UIImage(systemName: "clock.fill")
        symbolView.tintColor = .systemOrange
      case .stale:
        titleLabel.text = "C3XL 已连接 · 导航信息过期"
        symbolView.image = UIImage(systemName: "exclamationmark.triangle.fill")
        symbolView.tintColor = .systemOrange
      }
    case .scanning, .discovered:
      titleLabel.text = "正在连接 C3XL"
      detailLabel.text = status.detail
      symbolView.image = UIImage(systemName: "wifi")
      symbolView.tintColor = .systemBlue
    case .error:
      titleLabel.text = "C3XL 连接中断"
      detailLabel.text = status.detail
      symbolView.image = UIImage(systemName: "wifi.exclamationmark")
      symbolView.tintColor = .systemOrange
    case .stopped:
      titleLabel.text = "C3XL 尚未连接"
      detailLabel.text = "可在设置中重新连接设备"
      symbolView.image = UIImage(systemName: "wifi.slash")
      symbolView.tintColor = .secondaryLabel
    }
    accessibilityLabel = [titleLabel.text, detailLabel.text].compactMap { $0 }.joined(separator: "，")
  }
}
