import UIKit

final class RoutePlanningViewController: UIViewController {
  private let destination: Destination
  private let manager = AMapNaviDriveManager.sharedInstance()
  private let driveView = AMapNaviDriveView()
  private let tableView = UITableView(frame: .zero, style: .insetGrouped)
  private let startButton = UIButton(type: .system)
  private let simulationButton = UIButton(type: .system)
  private let statusLabel = UILabel()
  private var routes: [(id: Int, route: AMapNaviRoute)] = []
  private var selectedRouteID: Int?

  init(destination: Destination) {
    self.destination = destination
    super.init(nibName: nil, bundle: nil)
  }

  @available(*, unavailable)
  required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

  override func viewDidLoad() {
    super.viewDidLoad()
    title = destination.name
    view.backgroundColor = .systemBackground
    configureManager()
    configureUI()
    calculateRoutes()
  }

  deinit {
    manager.removeDataRepresentative(driveView)
    manager.removeEventListener(self)
  }

  private func configureManager() {
    manager.addEventListener(self)
    manager.addDataRepresentative(driveView)
    manager.setMultipleRouteNaviMode(true)
    manager.isUseInternalTTS = true
    manager.isUseTextPlay = true
    manager.allowsBackgroundLocationUpdates = true
    manager.pausesLocationUpdatesAutomatically = false
    NavigationSpeech.apply(NavigationSpeechSettings.shared.mode)
    driveView.autoZoomMapLevel = true
    driveView.showGreyAfterPass = true
    driveView.trackingMode = .carNorth
    driveView.showUIElements = false
  }

  private func configureUI() {
    driveView.translatesAutoresizingMaskIntoConstraints = false
    tableView.translatesAutoresizingMaskIntoConstraints = false
    tableView.dataSource = self
    tableView.delegate = self
    tableView.register(UITableViewCell.self, forCellReuseIdentifier: "route")

    statusLabel.translatesAutoresizingMaskIntoConstraints = false
    statusLabel.text = "正在规划多条路线…"
    statusLabel.textAlignment = .center
    statusLabel.numberOfLines = 2
    statusLabel.textColor = .secondaryLabel

    startButton.translatesAutoresizingMaskIntoConstraints = false
    var configuration = UIButton.Configuration.filled()
    configuration.title = "开始语音导航"
    configuration.cornerStyle = .large
    startButton.configuration = configuration
    startButton.isEnabled = false
    startButton.addTarget(self, action: #selector(startNavigation), for: .touchUpInside)

    var simulationConfiguration = UIButton.Configuration.filled()
    simulationConfiguration.title = "模拟导航"
    simulationConfiguration.cornerStyle = .large
    simulationConfiguration.baseBackgroundColor = .systemIndigo
    simulationButton.configuration = simulationConfiguration
    simulationButton.isEnabled = false
    simulationButton.addTarget(self, action: #selector(startSimulation), for: .touchUpInside)

    let startControls = UIStackView(arrangedSubviews: [startButton, simulationButton])
    startControls.translatesAutoresizingMaskIntoConstraints = false
    startControls.axis = .horizontal
    startControls.spacing = 12
    startControls.distribution = .fillEqually

    view.addSubview(driveView)
    view.addSubview(tableView)
    view.addSubview(statusLabel)
    view.addSubview(startControls)
    NSLayoutConstraint.activate([
      driveView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
      driveView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      driveView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      driveView.heightAnchor.constraint(equalTo: view.heightAnchor, multiplier: 0.42),
      tableView.topAnchor.constraint(equalTo: driveView.bottomAnchor),
      tableView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
      tableView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
      statusLabel.topAnchor.constraint(equalTo: tableView.bottomAnchor, constant: 4),
      statusLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
      statusLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),
      startControls.topAnchor.constraint(equalTo: statusLabel.bottomAnchor, constant: 8),
      startControls.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 20),
      startControls.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -20),
      startControls.heightAnchor.constraint(equalToConstant: 50),
      startControls.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -8),
    ])
  }

  private func calculateRoutes() {
    let end = AMapNaviPOIInfo()
    end.name = destination.name
    end.mid = destination.poiID
    end.locPoint = AMapNaviPoint.location(withLatitude: destination.latitude, longitude: destination.longitude)
    let accepted = manager.calculateDriveRoute(
      withStart: nil,
      end: end,
      wayPOIInfos: nil,
      drivingStrategy: AMapNaviDrivingStrategy(rawValue: 10)!
    )
    if !accepted {
      statusLabel.text = "算路参数未被高德 SDK 接受"
    }
  }

  @objc private func startNavigation() {
    beginNavigation(mode: .realtime)
  }

  @objc private func startSimulation() {
    beginNavigation(mode: .simulation)
  }

  private func beginNavigation(mode: NavigationStartMode) {
    guard let routeID = selectedRouteID, manager.selectNaviRoute(withRouteID: routeID) else {
      statusLabel.text = "无法选择当前路线"
      return
    }
    if mode == .realtime {
      NavigationStateStore.shared.startRealtime()
    } else {
      NavigationStateStore.shared.startSimulation()
    }
    navigationController?.pushViewController(
      NavigationViewController(destination: destination, startMode: mode),
      animated: true
    )
  }

  private func refreshRoutes() {
    routes = (manager.naviRoutes ?? [:])
      .map { (id: $0.key.intValue, route: $0.value) }
      .sorted { $0.id < $1.id }
      .prefix(3)
      .map { $0 }
    selectedRouteID = routes.first(where: { $0.id == manager.naviRouteID })?.id ?? routes.first?.id
    if let selectedRouteID { _ = manager.selectNaviRoute(withRouteID: selectedRouteID) }
    NavigationStateStore.shared.routeCalculated()
    startButton.isEnabled = selectedRouteID != nil
    simulationButton.isEnabled = selectedRouteID != nil
    statusLabel.text = routes.isEmpty ? "没有可用路线" : "已返回 \(routes.count) 条路线，请选择后开始导航"
    tableView.reloadData()
  }
}

extension RoutePlanningViewController: AMapNaviDriveManagerDelegate {
  func driveManager(onCalculateRouteSuccess driveManager: AMapNaviDriveManager) { refreshRoutes() }

  func driveManager(_ driveManager: AMapNaviDriveManager, onCalculateRouteFailure error: Error) {
    statusLabel.text = "路线规划失败：\(error.localizedDescription)"
  }
}

extension RoutePlanningViewController: UITableViewDataSource, UITableViewDelegate {
  func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int { routes.count }

  func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
    let cell = tableView.dequeueReusableCell(withIdentifier: "route", for: indexPath)
    let item = routes[indexPath.row]
    var configuration = cell.defaultContentConfiguration()
    configuration.text = indexPath.row == 0 ? "推荐路线" : "备选路线 \(indexPath.row + 1)"
    configuration.secondaryText = String(
      format: "%d 分钟 · %.1f 公里 · 过路费 ¥%d · %d 个红绿灯",
      Int(ceil(Double(item.route.routeTime) / 60)),
      Double(item.route.routeLength) / 1_000,
      item.route.routeTollCost,
      item.route.routeTrafficLightCount
    )
    cell.contentConfiguration = configuration
    cell.accessoryType = selectedRouteID == item.id ? .checkmark : .none
    return cell
  }

  func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
    tableView.deselectRow(at: indexPath, animated: true)
    let routeID = routes[indexPath.row].id
    if manager.selectNaviRoute(withRouteID: routeID) {
      selectedRouteID = routeID
      tableView.reloadData()
    }
  }
}
