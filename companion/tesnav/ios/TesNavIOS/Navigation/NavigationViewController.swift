import UIKit

enum NavigationStartMode {
  case realtime
  case simulation
}

final class NavigationViewController: UIViewController {
  private let destination: Destination
  private let startMode: NavigationStartMode
  private let manager = AMapNaviDriveManager.sharedInstance()
  private let driveView = AMapNaviDriveView()
  private let connectionView = ConnectionStatusView(compact: true)
  private let speechButton = UIButton(type: .system)
  private var telemetry: NavigationTelemetry?
  private var started = false
  private var speechPaused: Bool { NavigationSpeechSettings.shared.mode == .muted }
  private var simulationPaused = false
  private let simulationButton = UIButton(type: .system)

  init(destination: Destination, startMode: NavigationStartMode = .realtime) {
    self.destination = destination
    self.startMode = startMode
    super.init(nibName: nil, bundle: nil)
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidLoad() {
    super.viewDidLoad()
    title = destination.name
    view.backgroundColor = .systemGroupedBackground
    navigationItem.hidesBackButton = true
    navigationItem.rightBarButtonItem = UIBarButtonItem(
      image: UIImage(systemName: "gearshape"), style: .plain, target: self, action: #selector(showNavigationSettings)
    )
    navigationItem.rightBarButtonItem?.accessibilityLabel = "导航设置"
    configureUI()
    configureNavigation()
  }

  override func viewDidAppear(_ animated: Bool) {
    super.viewDidAppear(animated)
    updateSpeechButton()
    guard !started else { return }
    started = true
    NavAssistClient.shared.requestRediscovery()
    let accepted = startMode == .realtime ? manager.startGPSNavi() : manager.startEmulatorNavi()
    NavigationSpeech.apply(NavigationSpeechSettings.shared.mode)
    if !accepted {
      NavigationStateStore.shared.navigationStartFailed()
      showStartFailure()
    }
  }

  deinit {
    manager.removeDataRepresentative(driveView)
    manager.removeEventListener(self)
  }

  private func configureNavigation() {
    manager.isUseInternalTTS = true
    manager.isUseTextPlay = true
    NavigationSpeech.apply(NavigationSpeechSettings.shared.mode)
    manager.allowsBackgroundLocationUpdates = true
    manager.pausesLocationUpdatesAutomatically = false
    manager.addDataRepresentative(driveView)
    manager.addEventListener(self)
    telemetry = NavigationTelemetry(manager: manager)
    driveView.delegate = self
    driveView.autoZoomMapLevel = true
    driveView.showGreyAfterPass = true
    driveView.trackingMode = .carNorth
  }

  private func configureUI() {
    driveView.translatesAutoresizingMaskIntoConstraints = false
    connectionView.translatesAutoresizingMaskIntoConstraints = false

    let stopButton = UIButton(type: .system)
    stopButton.translatesAutoresizingMaskIntoConstraints = false
    var stopConfiguration = UIButton.Configuration.filled()
    stopConfiguration.title = "结束导航"
    stopConfiguration.image = UIImage(systemName: "xmark.circle.fill")
    stopConfiguration.imagePadding = 8
    stopConfiguration.cornerStyle = .medium
    stopConfiguration.baseForegroundColor = .white
    stopConfiguration.baseBackgroundColor = .systemRed
    stopButton.configuration = stopConfiguration
    stopButton.addTarget(self, action: #selector(stopNavigation), for: .touchUpInside)

    speechButton.translatesAutoresizingMaskIntoConstraints = false
    var speechConfiguration = UIButton.Configuration.tinted()
    speechConfiguration.title = "语音开启"
    speechConfiguration.image = UIImage(systemName: "speaker.wave.2.fill")
    speechConfiguration.imagePadding = 8
    speechConfiguration.cornerStyle = .medium
    speechConfiguration.baseForegroundColor = .systemBlue
    speechButton.configuration = speechConfiguration
    speechButton.addTarget(self, action: #selector(toggleSpeech), for: .touchUpInside)

    simulationButton.translatesAutoresizingMaskIntoConstraints = false
    var simulationConfiguration = UIButton.Configuration.tinted()
    simulationConfiguration.title = "暂停"
    simulationConfiguration.image = UIImage(systemName: "pause.fill")
    simulationConfiguration.imagePadding = 6
    simulationConfiguration.baseForegroundColor = .systemIndigo
    simulationButton.configuration = simulationConfiguration
    simulationButton.addTarget(self, action: #selector(toggleSimulation), for: .touchUpInside)
    simulationButton.isHidden = startMode != .simulation

    let controls = UIStackView(arrangedSubviews: [speechButton, simulationButton, stopButton])
    controls.translatesAutoresizingMaskIntoConstraints = false
    controls.axis = .horizontal
    controls.spacing = 10
    controls.distribution = .fillEqually

    let toolbar = UIView()
    toolbar.translatesAutoresizingMaskIntoConstraints = false
    toolbar.backgroundColor = .secondarySystemGroupedBackground
    toolbar.addSubview(controls)
    let separator = UIView()
    separator.translatesAutoresizingMaskIntoConstraints = false
    separator.backgroundColor = .separator
    toolbar.addSubview(separator)

    view.addSubview(driveView)
    view.addSubview(connectionView)
    view.addSubview(toolbar)
    NSLayoutConstraint.activate([
      connectionView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 8),
      connectionView.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 12),
      connectionView.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -12),
      driveView.topAnchor.constraint(equalTo: connectionView.bottomAnchor, constant: 8),
      driveView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      driveView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      driveView.bottomAnchor.constraint(equalTo: toolbar.topAnchor),
      toolbar.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      toolbar.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      toolbar.bottomAnchor.constraint(equalTo: view.bottomAnchor),
      controls.topAnchor.constraint(equalTo: toolbar.topAnchor, constant: 12),
      controls.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 16),
      controls.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -16),
      controls.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -12),
      controls.heightAnchor.constraint(greaterThanOrEqualToConstant: 50),
      separator.topAnchor.constraint(equalTo: toolbar.topAnchor),
      separator.leadingAnchor.constraint(equalTo: toolbar.leadingAnchor),
      separator.trailingAnchor.constraint(equalTo: toolbar.trailingAnchor),
      separator.heightAnchor.constraint(equalToConstant: 0.5),
    ])
  }

  @objc private func toggleSpeech() {
    let settings = NavigationSpeechSettings.shared
    let next = speechPaused ? settings.resumedMode : NavigationSpeechMode.muted
    guard NavigationSpeech.apply(next) else { return }
    settings.save(next)
    updateSpeechButton()
  }

  private func updateSpeechButton() {
    if speechPaused {
      speechButton.configuration?.title = "语音关闭"
      speechButton.configuration?.image = UIImage(systemName: "speaker.slash.fill")
    } else {
      speechButton.configuration?.title = NavigationSpeechSettings.shared.mode == .concise ? "简洁播报" : "详细播报"
      speechButton.configuration?.image = UIImage(systemName: "speaker.wave.2.fill")
    }
  }

  @objc private func toggleSimulation() {
    guard startMode == .simulation else { return }
    simulationPaused.toggle()
    if simulationPaused {
      manager.pauseNavi()
      simulationButton.configuration?.title = "继续"
      simulationButton.configuration?.image = UIImage(systemName: "play.fill")
    } else {
      manager.resumeNavi()
      simulationButton.configuration?.title = "暂停"
      simulationButton.configuration?.image = UIImage(systemName: "pause.fill")
    }
  }

  @objc private func stopNavigation() {
    finishNavigation()
  }

  private func finishNavigation() {
    _ = manager.stopNavi()
    NavigationStateStore.shared.stop()
    navigationController?.popToRootViewController(animated: true)
  }

  @objc private func showNavigationSettings() {
    guard presentedViewController == nil else { return }
    let sheet = UIAlertController(title: "导航设置", message: nil, preferredStyle: .actionSheet)
    sheet.addAction(UIAlertAction(title: "语音播报频次", style: .default) { [weak self] _ in
      self?.navigationController?.pushViewController(NavigationSpeechViewController(), animated: true)
    })
    sheet.addAction(UIAlertAction(title: speechPaused ? "恢复语音" : "静音", style: .default) { [weak self] _ in
      self?.toggleSpeech()
    })
    sheet.addAction(UIAlertAction(
      title: driveView.autoZoomMapLevel ? "关闭自动缩放" : "开启自动缩放",
      style: .default
    ) { [weak self] _ in
      guard let self else { return }
      self.driveView.autoZoomMapLevel.toggle()
    })
    sheet.addAction(UIAlertAction(title: "重新连接 C3XL", style: .default) { _ in
      NavAssistClient.shared.requestRediscovery()
    })
    sheet.addAction(UIAlertAction(title: "取消", style: .cancel))
    sheet.popoverPresentationController?.barButtonItem = navigationItem.rightBarButtonItem
    present(sheet, animated: true)
  }

  private func showStartFailure() {
    let alert = UIAlertController(title: "无法开始导航", message: "高德导航没有接受当前路线，请返回重新规划。", preferredStyle: .alert)
    alert.addAction(UIAlertAction(title: "返回", style: .default) { [weak self] _ in
      self?.navigationController?.popViewController(animated: true)
    })
    present(alert, animated: true)
  }
}

extension NavigationViewController: AMapNaviDriveManagerDelegate {
  func driveManager(onArrivedDestination driveManager: AMapNaviDriveManager) {
    title = "已到达目的地"
    speechButton.isEnabled = false
  }

  func driveManager(_ driveManager: AMapNaviDriveManager, onCalculateRouteFailure error: Error) {
    title = "路线重算失败"
  }
}

extension NavigationViewController: AMapNaviDriveViewDelegate {
  func driveViewCloseButtonClicked(_ driveView: AMapNaviDriveView) {
    finishNavigation()
  }

  func driveViewMoreButtonClicked(_ driveView: AMapNaviDriveView) {
    showNavigationSettings()
  }
}
