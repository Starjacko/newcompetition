from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """All values that are likely to change while tuning the strategy."""

    stone_batch_size: int = 6
    upper_wall_ratio: float = 0.5
    lower_wall_ratio: float = 0.5
    return_safety_margin: int = 4
    task_count_target: int = 6
    vendor_mine_order: tuple[str, ...] = ("iron", "copper", "stone")
    weapon_build_order: tuple[str, ...] = ("rocket", "railgun", "gatling")
    upgrade_queue: tuple[tuple[str, str], ...] = (
        # 先把武器升级完成，再投入基地和围墙升级资源。
        ("WeaponUpgradeVoucher1", "rocket"),
        ("WeaponUpgradeVoucher1", "railgun"),
        ("WeaponUpgradeVoucher1", "gatling"),
        ("WeaponUpgradeVoucher2", "rocket"),
        ("WeaponUpgradeVoucher2", "railgun"),
        ("WeaponUpgradeVoucher2", "gatling"),
        ("StationUpgradeVoucher1", "station"),
        ("StationUpgradeVoucher2", "station"),
        ("WallUpgradeVoucher1", "front_wall"),
        ("WallUpgradeVoucher2", "front_wall"),
    )


DEFAULT_CONFIG = StrategyConfig()
