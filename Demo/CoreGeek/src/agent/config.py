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
        ("WeaponUpgradeVoucher1", "rocket"),
        ("StationUpgradeVoucher1", "station"),
        ("WeaponUpgradeVoucher2", "rocket"),
        ("WeaponUpgradeVoucher1", "railgun"),
        ("WallUpgradeVoucher1", "front_wall"),
        ("StationUpgradeVoucher2", "station"),
        ("WeaponUpgradeVoucher2", "railgun"),
        ("WallUpgradeVoucher2", "front_wall"),
        ("WeaponUpgradeVoucher1", "gatling"),
    )


DEFAULT_CONFIG = StrategyConfig()
