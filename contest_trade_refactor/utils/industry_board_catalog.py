"""东财 / 同花顺 / 腾讯财经行业板块名称与代码对照。

industry_map 用的是东财二级/三级名（通信、银行Ⅱ、数字芯片设计）。
同花顺指数只认约 90 个一级名（通信设备、银行），腾讯 rank 用 pt0180xxxx。
名称和代码写在 industry_board_constants，运行时默认不请求板块列表。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger

from utils.industry_board_constants import (
    INDUSTRY_BOARD_RESOLVE,
    TENCENT_INDUSTRY_CODES,
    THS_INDUSTRY_CODES,
)

_LEVEL_SUFFIXES = ("Ⅲ", "Ⅱ", "Ⅰ", "III", "II", "I")

# 查询名 -> 各源按优先级尝试的板块名。解析时先查 INDUSTRY_BOARD_RESOLVE 常量。
BOARD_NAME_ALIASES: dict[str, list[str]] = {
    "IT服务": ["IT服务Ⅱ", "IT服务"],
    "IT服务Ⅱ": ["IT服务Ⅱ", "IT服务"],
    "交通运输": ["铁路公路", "公路铁路运输", "航运港口", "航空机场", "物流"],
    "产业地产": ["房地产开发", "房地产"],
    "人力资源服务": ["专业服务", "其他社会服务"],
    "人工景区": ["旅游及景区", "旅游及酒店"],
    "会展服务": ["专业服务", "其他社会服务"],
    "住宅开发": ["房地产开发", "房地产"],
    "体外诊断": ["医疗器械"],
    "体育Ⅲ": ["文娱用品", "其他社会服务"],
    "信托": ["多元金融"],
    "光伏发电": ["光伏设备"],
    "公交": ["铁路公路", "公路铁路运输"],
    "公用事业": ["电力", "燃气Ⅱ", "燃气"],
    "公路货运": ["物流"],
    "其他家电Ⅱ": ["小家电", "白色家电"],
    "其他石化": ["炼化及贸易", "石油加工贸易", "化学制品"],
    "其他酒类": ["非白酒", "白酒Ⅱ", "白酒"],
    "农林牧渔": ["养殖业", "种植业", "种植业与林业", "农产品加工"],
    "冰洗": ["白色家电"],
    "分立器件": ["半导体"],
    "制冷空调设备": ["白色家电"],
    "医疗美容": ["美容护理"],
    "医疗设备": ["医疗器械"],
    "医美耗材": ["美容护理"],
    "医药生物": ["化学制药", "生物制品", "医疗器械", "医疗服务", "中药Ⅱ", "中药", "医药商业"],
    "医院": ["医疗服务"],
    "卫浴制品": ["家居用品"],
    "印刷包装机械": ["专用设备"],
    "印染": ["纺织制造"],
    "厨房电器": ["厨卫电器"],
    "商用载货车": ["商用车"],
    "国防军工": ["军工电子Ⅱ", "军工电子", "航空装备Ⅱ", "航天装备Ⅱ", "地面兵装Ⅱ", "军工装备"],
    "国际工程": ["专业工程", "基础建设"],
    "图片媒体": ["数字媒体", "文化传媒", "出版"],
    "基建市政工程": ["基础建设", "专业工程"],
    "基础化工": ["化学制品", "化学原料", "化学纤维", "农化制品", "塑料"],
    "娱乐用品": ["文娱用品", "家居用品"],
    "宠物食品": ["饲料", "农产品加工", "食品加工"],
    "家用电器": ["白色家电", "黑色家电", "小家电", "厨卫电器"],
    "个护小家电": ["小家电"],
    "影视动漫制作": ["影视院线", "数字媒体"],
    "数字芯片设计": ["半导体"],
    "文字媒体": ["出版", "文化传媒"],
    "有机硅": ["化学制品"],
    "有色金属": ["工业金属", "能源金属", "贵金属", "小金属"],
    "期货": ["多元金融"],
    "机械设备": ["专用设备", "通用设备", "自动化设备", "工程机械"],
    "果蔬加工": ["农产品加工", "食品加工", "食品加工制造"],
    "棉纺": ["纺织制造"],
    "模拟芯片设计": ["半导体"],
    "横向通用软件": ["软件开发"],
    "氟化工": ["化学制品"],
    "氨纶": ["化学纤维"],
    "氯碱": ["化学制品"],
    "水产养殖": ["渔业", "养殖业"],
    "汽车": ["汽车零部件", "乘用车", "商用车", "汽车整车", "汽车服务"],
    "汽车电子电气系统": ["汽车零部件"],
    "涂料油墨": ["化学制品"],
    "焦煤": ["煤炭开采", "煤炭开采加工"],
    "熟食": ["食品加工", "食品加工制造"],
    "物业管理": ["房地产服务", "房地产"],
    "玻纤制造": ["玻璃玻纤", "非金属材料Ⅱ", "非金属材料"],
    "生活用纸": ["造纸"],
    "电商服务": ["互联网电商"],
    "电子": ["半导体", "消费电子", "光学光电子", "元件", "其他电子Ⅱ", "其他电子"],
    "白银": ["贵金属"],
    "石油石化": ["炼化及贸易", "油服工程", "石油加工贸易"],
    "磨具磨料": ["专用设备"],
    "稀土": ["小金属", "金属新材料", "工业金属"],
    "端到端供应链服务": ["物流"],
    "管材": ["普钢", "钢铁"],
    "粘胶": ["化学纤维"],
    "纯碱": ["化学制品"],
    "纸包装": ["包装印刷"],
    "纺织服装设备": ["专用设备"],
    "纺织服饰": ["服装家纺", "纺织制造"],
    "线下药店": ["医药商业"],
    "聚氨酯": ["化学制品"],
    "肉鸡养殖": ["养殖业"],
    "胶黏剂及胶带": ["化学制品"],
    "膜材料": ["化学制品"],
    "航空运输": ["航空机场", "机场航运"],
    "营销代理": ["广告营销"],
    "血液制品": ["生物制品"],
    "视频媒体": ["数字媒体", "电视广播Ⅱ", "文化传媒"],
    "诊断服务": ["医疗服务"],
    "车身附件及饰件": ["汽车零部件"],
    "轮胎轮毂": ["汽车零部件"],
    "轻工制造": ["家居用品", "包装印刷", "造纸"],
    "输变电设备": ["电网设备"],
    "运动服装": ["服装家纺"],
    "通信": ["通信设备", "通信服务"],
    "通信应用增值服务": ["通信服务"],
    "通信终端及配件": ["通信设备"],
    "金属包装": ["包装印刷"],
    "金融控股": ["多元金融"],
    "钛白粉": ["化学制品"],
    "钟表珠宝": ["饰品", "零售"],
    "铁矿石": ["冶钢原料"],
    "铅锌": ["工业金属", "小金属"],
    "铜": ["工业金属"],
    "锂": ["能源金属"],
    "长材": ["普钢", "钢铁"],
    "集成电路制造": ["半导体"],
    "非运动服装": ["服装家纺"],
    "非银金融": ["证券Ⅱ", "证券", "保险Ⅱ", "保险", "多元金融"],
    "预加工食品": ["食品加工", "食品加工制造"],
    "风力发电": ["风电设备"],
    "风电整机": ["风电设备"],
    "食品饮料": ["食品加工", "食品加工制造", "饮料乳品", "饮料制造", "白酒Ⅱ", "白酒"],
    "银行Ⅱ": ["股份制银行Ⅱ", "国有大型银行Ⅱ", "城商行Ⅱ", "农商行Ⅱ", "银行"],
    "银行": ["银行", "股份制银行Ⅱ", "国有大型银行Ⅱ"],
    "房地产": ["房地产开发", "房地产", "房地产服务"],
    "钢铁": ["普钢", "特钢Ⅱ", "钢铁"],
    "电力设备": ["电网设备", "光伏设备", "电池", "电机Ⅱ", "电机", "风电设备", "其他电源设备Ⅱ", "其他电源设备"],
    "计算机": ["计算机设备", "软件开发", "IT服务Ⅱ", "IT服务"],
    "煤炭": ["煤炭开采", "煤炭开采加工"],
    "煤炭开采": ["煤炭开采", "煤炭开采加工"],
    "塑料": ["塑料", "塑料制品"],
    "炼化及贸易": ["炼化及贸易", "石油加工贸易"],
    "农商行": ["农商行Ⅱ", "银行"],
    "股份制银行": ["股份制银行Ⅱ", "银行"],
    "国有大型银行": ["国有大型银行Ⅱ", "银行"],
    "城商行": ["城商行Ⅱ", "银行"],
    "证券": ["证券Ⅱ", "证券"],
    "保险": ["保险Ⅱ", "保险"],
    "中药": ["中药Ⅱ", "中药"],
    "白酒": ["白酒Ⅱ", "白酒"],
    "燃气": ["燃气Ⅱ", "燃气"],
    "综合": ["综合Ⅱ", "综合"],
    "游戏": ["游戏Ⅱ", "游戏"],
    "电机": ["电机Ⅱ", "电机"],
    "其他电源设备": ["其他电源设备Ⅱ", "其他电源设备"],
    "其他电子": ["其他电子Ⅱ", "其他电子"],
    "非金属材料": ["非金属材料Ⅱ", "非金属材料"],
    "环保设备": ["环保设备Ⅱ", "环保设备"],
    "贸易": ["贸易Ⅱ", "贸易"],
    "专业连锁": ["专业连锁Ⅱ", "一般零售", "零售"],
    "装修装饰": ["装修装饰Ⅱ", "建筑装饰"],
    "轨交设备": ["轨交设备Ⅱ", "轨交设备"],
    "照明设备": ["照明设备Ⅱ"],
    "家电零部件": ["家电零部件Ⅱ"],
    "焦炭": ["焦炭Ⅱ"],
    "特钢": ["特钢Ⅱ", "钢铁"],
    "动物保健": ["动物保健Ⅱ"],
    "电子化学品": ["电子化学品Ⅱ", "电子化学品"],
    "调味发酵品": ["调味发酵品Ⅱ"],
    "工程咨询服务": ["工程咨询服务Ⅱ"],
    "军工电子": ["军工电子Ⅱ", "军工电子"],
    "航空装备": ["航空装备Ⅱ", "军工装备"],
    "航天装备": ["航天装备Ⅱ", "军工装备"],
    "航海装备": ["航海装备Ⅱ", "军工装备"],
    "地面兵装": ["地面兵装Ⅱ", "军工装备"],
    "房屋建设": ["房屋建设Ⅱ", "基础建设"],
    "电视广播": ["电视广播Ⅱ", "文化传媒"],
    "传媒": ["数字媒体", "出版", "影视院线", "文化传媒", "游戏Ⅱ"],
    "医疗美容": ["化妆品", "个护用品", "美容护理"],
    "医美耗材": ["化妆品", "个护用品", "美容护理"],
    "美容护理": ["化妆品", "个护用品", "美容护理"],
    "商贸零售": ["一般零售", "专业连锁Ⅱ", "零售"],
    "建筑材料": ["水泥", "装修建材", "玻璃玻纤", "建筑材料"],
    "建筑装饰": ["装修装饰Ⅱ", "建筑装饰"],
    "旅游零售Ⅱ": ["一般零售", "旅游及景区", "零售"],
    "林业Ⅱ": ["种植业", "种植业与林业"],
    "汽车综合服务": ["汽车服务", "汽车服务及其他"],
    "油品石化贸易": ["炼化及贸易", "石油加工贸易"],
    "电能综合服务": ["电力"],
    "社会服务": ["专业服务", "教育", "其他社会服务"],
    "综合包装": ["包装印刷"],
    "综合电商": ["互联网电商"],
    "乘用车": ["乘用车", "汽车整车"],
    "电动乘用车": ["乘用车", "汽车整车"],
    "商用车": ["商用车", "汽车整车"],
    "商用载货车": ["商用车", "汽车整车"],
    "摩托车": ["摩托车及其他", "汽车整车"],
    "摩托车及其他": ["摩托车及其他", "汽车整车"],
    "其他专业工程": ["专业工程", "基础建设", "建筑装饰"],
    "国际工程": ["专业工程", "基础建设", "建筑装饰"],
    "基建市政工程": ["基础建设", "专业工程", "建筑装饰"],
    "基础建设": ["基础建设", "专业工程", "建筑装饰"],
    "房屋建设Ⅱ": ["房屋建设Ⅱ", "基础建设", "建筑装饰"],
    "冶钢原料": ["冶钢原料", "钢铁"],
    "铁矿石": ["冶钢原料", "钢铁"],
    "动物保健Ⅱ": ["动物保健Ⅱ", "养殖业", "生物制品"],
    "品牌化妆品": ["化妆品", "美容护理"],
    "广告营销": ["广告营销", "文化传媒"],
    "营销代理": ["广告营销", "文化传媒"],
    "数字媒体": ["数字媒体", "文化传媒"],
    "文娱用品": ["文娱用品", "家居用品"],
    "旅游及景区": ["旅游及景区", "旅游及酒店"],
    "水产饲料": ["饲料", "农产品加工"],
    "饲料": ["饲料", "农产品加工"],
    "水泥": ["水泥", "建筑材料"],
    "水泥制造": ["水泥", "建筑材料"],
    "渔业": ["渔业", "养殖业"],
    "玻璃玻纤": ["玻璃玻纤", "非金属材料"],
    "综合环境治理": ["环境治理"],
    "航空机场": ["航空机场", "机场航运"],
    "调味发酵品Ⅱ": ["调味发酵品Ⅱ", "食品加工", "食品加工制造"],
    "铁路公路": ["铁路公路", "公路铁路运输"],
    "餐饮": ["酒店餐饮", "旅游及酒店"],
    "饰品": ["饰品", "零售"],
}

KEYWORD_PARENTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("芯片", "集成电路", "分立器件"), ("半导体",)),
    (("锂",), ("能源金属",)),
    (("铜", "铅锌", "铝"), ("工业金属",)),
    (("银", "黄金", "白银"), ("贵金属",)),
    (("铁矿", "冶钢"), ("冶钢原料",)),
    (("风电",), ("风电设备",)),
    (("光伏",), ("光伏设备",)),
    (("银行",), ("银行", "股份制银行Ⅱ")),
    (("通信",), ("通信设备", "通信服务")),
    (("食品",), ("食品加工", "食品加工制造")),
    (("饮料", "乳品"), ("饮料乳品", "饮料制造")),
)


@dataclass(frozen=True)
class BoardResolution:
    query: str
    tencent_name: Optional[str] = None
    tencent_code: Optional[str] = None
    ths_name: Optional[str] = None
    ths_code: Optional[str] = None

    @property
    def has_tencent(self) -> bool:
        return bool(self.tencent_code)

    @property
    def has_ths(self) -> bool:
        return bool(self.ths_name)


_CATALOG: Optional[dict[str, Any]] = None


def _norm_name(name: str) -> str:
    text = str(name or "").strip().replace(" ", "")
    return text.replace("（", "(").replace("）", ")")


def strip_level_suffix(name: str) -> str:
    text = _norm_name(name)
    for suffix in _LEVEL_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)].strip()
    return text


def _strip_other_prefix(name: str) -> str:
    text = _norm_name(name)
    if text.startswith("其他") and len(text) > 2:
        return text[2:]
    return text


def _name_index(items: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw, value in items.items():
        key = _norm_name(raw)
        if key and key not in out:
            out[key] = raw
        stripped = strip_level_suffix(raw)
        if stripped and stripped not in out:
            out[stripped] = raw
    return out


def _candidate_names(query: str) -> list[str]:
    raw = _norm_name(query)
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def add(name: str) -> None:
        key = _norm_name(name)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(key)

    add(raw)
    add(strip_level_suffix(raw))
    add(_strip_other_prefix(raw))
    add(strip_level_suffix(_strip_other_prefix(raw)))
    for key in (raw, strip_level_suffix(raw), str(query).strip()):
        for alias in BOARD_NAME_ALIASES.get(key, []):
            add(alias)
            add(strip_level_suffix(alias))
    return out


def _lookup_name(query: str, source_map: dict[str, str]) -> Optional[str]:
    if not source_map:
        return None
    index = _name_index(source_map)
    for cand in _candidate_names(query):
        hit = index.get(cand)
        if hit:
            return hit

    qn = _norm_name(query)
    qs = strip_level_suffix(query)
    for prefixes, parents in KEYWORD_PARENTS:
        if any(p in qn or p in qs for p in prefixes):
            for parent in parents:
                hit = index.get(_norm_name(parent))
                if hit:
                    return hit

    contains: list[str] = []
    for raw in source_map:
        rn = _norm_name(raw)
        rs = strip_level_suffix(raw)
        if len(qn) >= 2 and (qn in rn or rn in qn or (qs and qs in rs)):
            contains.append(raw)
    if len(contains) == 1:
        return contains[0]
    return None


def _builtin_catalog() -> dict[str, Any]:
    return {
        "updated_at": "builtin",
        "tencent": dict(TENCENT_INDUSTRY_CODES),
        "ths": dict(THS_INDUSTRY_CODES),
    }


def load_catalog(*, refresh: bool = False) -> dict[str, Any]:
    global _CATALOG
    if _CATALOG is not None and not refresh:
        return _CATALOG
    if refresh:
        logger.warning("行业板块对照已固化为常量，忽略 refresh，不请求源站列表")
    _CATALOG = _builtin_catalog()
    return _CATALOG


def clear_catalog_cache() -> None:
    global _CATALOG
    _CATALOG = None


def _frozen_resolution(query: str) -> Optional[BoardResolution]:
    for cand in (*_candidate_names(query), str(query).strip()):
        ref = INDUSTRY_BOARD_RESOLVE.get(cand) or INDUSTRY_BOARD_RESOLVE.get(_norm_name(cand))
        if not ref:
            continue
        tencent_name, tencent_code, ths_name, ths_code = ref
        if tencent_code or ths_name:
            return BoardResolution(
                query=str(query or "").strip(),
                tencent_name=tencent_name,
                tencent_code=tencent_code,
                ths_name=ths_name,
                ths_code=ths_code,
            )
    return None


def resolve_industry_board(
    query: str,
    catalog: Optional[dict[str, Any]] = None,
) -> BoardResolution:
    name = str(query or "").strip()
    if not name:
        return BoardResolution(query="")
    if catalog is None:
        frozen = _frozen_resolution(name)
        if frozen is not None:
            return frozen
        data = load_catalog()
    else:
        data = catalog
    tencent_map = dict(data.get("tencent") or {})
    ths_map = dict(data.get("ths") or {})
    tencent_name = _lookup_name(name, tencent_map)
    ths_name = _lookup_name(name, ths_map)
    return BoardResolution(
        query=name,
        tencent_name=tencent_name,
        tencent_code=tencent_map.get(tencent_name) if tencent_name else None,
        ths_name=ths_name,
        ths_code=ths_map.get(ths_name) if ths_name else None,
    )
