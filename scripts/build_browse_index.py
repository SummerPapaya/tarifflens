#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成「按类别浏览」索引 —— 给不知道精确编码的读者一条从章到子目的路径。

    python3 scripts/build_browse_index.py            # 默认 data/
    python3 scripts/build_browse_index.py --out data

产出：
    hts-<tag>-browse.json.gz
      { tag, generated, chapters:[ { ch, zh, en, n, heads:[[h4, name, n_leaves], ...] } ] }

只索引到 4 位 heading 一级（约 1.2 万条 leaves 归约到 ~1.2k headings）。
更细的 6 位 / 8 位由前端拿到整章分片后本地分组 —— 分片本来就只有几 KB，
没必要再预生成一份会过期的大索引。

关于章标题：
  HTS 分片里没有章标题行（USITC 整表只有税则行），所以 97 个章名在这里写死。
  英文照 HS 官方章名；中文是常用参考译名，UI 上标注「参考译名」，
  不作为申报口径 —— 正式品名一律用分片里的 HTS 英文原文。
  第 77 章为空缺（HS 保留），不列出。
"""

import argparse
import glob
import gzip
import json
import os
import re
import sys

DEFAULT_OUT = "data"

# (中文参考译名, HS 英文官方章名)
CH_TITLES = {
 "01": ("活动物", "Live animals; animal products"),
 "02": ("肉及食用杂碎", "Meat and edible meat offal"),
 "03": ("鱼、甲壳动物、软体动物及其他水生无脊椎动物", "Fish and crustaceans, molluscs and other aquatic invertebrates"),
 "04": ("乳品；蛋品；天然蜂蜜；其他食用动物产品", "Dairy produce; birds' eggs; natural honey; edible products of animal origin, n.e.s."),
 "05": ("其他动物产品", "Products of animal origin, n.e.s."),
 "06": ("活树及其他活植物；鳞茎、根及类似品；插花及装饰用簇叶", "Live trees and other plants; bulbs, roots and the like; cut flowers and ornamental foliage"),
 "07": ("食用蔬菜、根及块茎", "Edible vegetables and certain roots and tubers"),
 "08": ("食用水果及坚果；柑橘属水果或甜瓜的果皮", "Edible fruit and nuts; peel of citrus fruit or melons"),
 "09": ("咖啡、茶、马黛茶及调味香料", "Coffee, tea, maté and spices"),
 "10": ("谷物", "Cereals"),
 "11": ("制粉工业产品；麦芽；淀粉；菊粉；小麦面筋", "Products of the milling industry; malt; starches; inulin; wheat gluten"),
 "12": ("含油子仁及果实；杂项子仁及果实；工业用或药用植物；稻草、秸秆及饲料", "Oil seeds and oleaginous fruits; miscellaneous grains, seeds and fruit; industrial or medicinal plants; straw and fodder"),
 "13": ("虫胶；树胶、树脂及其他植物液、汁", "Lac; gums, resins and other vegetable saps and extracts"),
 "14": ("编结用植物材料；其他植物产品", "Vegetable plaiting materials; vegetable products n.e.s."),
 "15": ("动、植物油、脂及其分解产品；精制食用油脂；动、植物蜡", "Animal or vegetable fats and oils and their cleavage products; prepared edible fats; animal or vegetable waxes"),
 "16": ("肉、鱼、甲壳动物、软体动物及其他水生无脊椎动物的制品", "Preparations of meat, of fish or of crustaceans, molluscs or other aquatic invertebrates"),
 "17": ("糖及糖食", "Sugars and sugar confectionery"),
 "18": ("可可及可可制品", "Cocoa and cocoa preparations"),
 "19": ("谷物、粮食粉、淀粉或乳的制品；糕饼点心", "Preparations of cereals, flour, starch or milk; pastrycooks' products"),
 "20": ("蔬菜、水果、坚果或植物其他部分的制品", "Preparations of vegetables, fruit, nuts or other parts of plants"),
 "21": ("杂项食品", "Miscellaneous edible preparations"),
 "22": ("饮料、酒及醋", "Beverages, spirits and vinegar"),
 "23": ("食品工业的残渣及废料；配制的动物饲料", "Residues and waste from the food industries; prepared animal fodder"),
 "24": ("烟草、烟草制品及烟草代用品", "Tobacco and manufactured tobacco substitutes"),
 "25": ("盐；硫磺；泥土及石料；石膏料、石灰及水泥", "Salt; sulphur; earths and stone; plastering materials, lime and cement"),
 "26": ("矿砂、矿渣及矿灰", "Ores, slag and ash"),
 "27": ("矿物燃料、矿物油及其蒸馏产品；沥青物质；矿物蜡", "Mineral fuels, mineral oils and products of their distillation; bituminous substances; mineral waxes"),
 "28": ("无机化学品；贵金属、稀土金属、放射性元素及其同位素的化合物", "Inorganic chemicals; organic or inorganic compounds of precious metals, of rare-earth metals, of radioactive elements or of isotopes"),
 "29": ("有机化学品", "Organic chemicals"),
 "30": ("药品", "Pharmaceutical products"),
 "31": ("肥料", "Fertilisers"),
 "32": ("鞣料浸膏及染料浸膏；鞣酸及其衍生物；染料、颜料及其他着色料；油漆及清漆；油灰及其他类似胶粘剂；墨水、油墨", "Tanning or dyeing extracts; tannins and their derivatives; dyes, pigments and other colouring matter; paints and varnishes; putty and other mastics; inks"),
 "33": ("精油及香膏；芳香料制品及化妆盥洗品", "Essential oils and resinoids; perfumery, cosmetic or toilet preparations"),
 "34": ("肥皂、有机表面活性剂、洗涤剂、润滑剂、人造蜡、调制蜡、光洁剂、蜡烛及类似品、塑型用膏、牙科用蜡及牙科用熟石膏制剂", "Soap, organic surface-active agents, washing preparations, lubricating preparations, artificial waxes, prepared waxes, polishing or scouring preparations, candles and similar articles, modelling pastes, dental waxes"),
 "35": ("蛋白类物质；改性淀粉；胶；酶", "Albuminoidal substances; modified starches; glues; enzymes"),
 "36": ("炸药；烟火制品；火柴；引火合金；易燃材料制品", "Explosives; pyrotechnic products; matches; pyrophoric alloys; certain combustible preparations"),
 "37": ("照相及电影用品", "Photographic or cinematographic goods"),
 "38": ("杂项化学产品", "Miscellaneous chemical products"),
 "39": ("塑料及其制品", "Plastics and articles thereof"),
 "40": ("橡胶及其制品", "Rubber and articles thereof"),
 "41": ("生皮（毛皮除外）及皮革", "Raw hides and skins (other than furskins) and leather"),
 "42": ("皮革制品；鞍具及挽具；旅行用品、手提包及类似容器；动物肠线制品", "Articles of leather; saddlery and harness; travel goods, handbags and similar containers; articles of animal gut"),
 "43": ("毛皮、人造毛皮及其制品", "Furskins and artificial fur; manufactures thereof"),
 "44": ("木及木制品；木炭", "Wood and articles of wood; wood charcoal"),
 "45": ("软木及软木制品", "Cork and articles of cork"),
 "46": ("稻草、秸秆、针茅或其他编结材料制品；篮筐及柳条编结品", "Manufactures of straw, of esparto or of other plaiting materials; basketware and wickerwork"),
 "47": ("木浆及其他纤维状纤维素浆；回收（废碎）纸或纸板", "Pulp of wood or of other fibrous cellulosic material; recovered (waste and scrap) paper or paperboard"),
 "48": ("纸及纸板；纸浆、纸或纸板制品", "Paper and paperboard; articles of paper pulp, of paper or of paperboard"),
 "49": ("书籍、报纸、印刷图画及其他印刷品；手稿、打字稿及设计图纸", "Printed books, newspapers, pictures and other products of the printing industry; manuscripts, typescripts and plans"),
 "50": ("蚕丝", "Silk"),
 "51": ("羊毛、动物细毛或粗毛；马毛纱线及其机织物", "Wool, fine or coarse animal hair; horsehair yarn and woven fabric"),
 "52": ("棉花", "Cotton"),
 "53": ("其他植物纺织纤维；纸纱线及其机织物", "Other vegetable textile fibres; paper yarn and woven fabrics of paper yarn"),
 "54": ("化学纤维长丝；化学纤维纺织材料制扁条及类似品", "Man-made filaments; strip and the like of man-made textile materials"),
 "55": ("化学纤维短纤", "Man-made staple fibres"),
 "56": ("絮胎、毡呢及无纺织物；特种纱线；线、绳、索、缆及其制品", "Wadding, felt and nonwovens; special yarns; twine, cordage, ropes and cables and articles thereof"),
 "57": ("地毯及纺织材料的其他铺地制品", "Carpets and other textile floor coverings"),
 "58": ("特种机织物；簇绒织物；花边；装饰毯；装饰带；刺绣品", "Special woven fabrics; tufted textile fabrics; lace; tapestries; trimmings; embroidery"),
 "59": ("浸渍、涂布、包覆或层压的纺织物；工业用纺织制品", "Impregnated, coated, covered or laminated textile fabrics; textile articles of a kind suitable for industrial use"),
 "60": ("针织物及钩编织物", "Knitted or crocheted fabrics"),
 "61": ("针织或钩编的服装及衣着附件", "Articles of apparel and clothing accessories, knitted or crocheted"),
 "62": ("非针织或非钩编的服装及衣着附件", "Articles of apparel and clothing accessories, not knitted or crocheted"),
 "63": ("其他纺织制成品；成套物品；旧衣着及旧纺织品；碎织物", "Other made-up textile articles; sets; worn clothing and worn textile articles; rags"),
 "64": ("鞋靴、护腿及类似品及其零件", "Footwear, gaiters and the like; parts of such articles"),
 "65": ("帽类及其零件", "Headgear and parts thereof"),
 "66": ("雨伞、阳伞、手杖、鞭子、马鞭及其零件", "Umbrellas, sun umbrellas, walking sticks, whips, riding crops and parts thereof"),
 "67": ("已加工羽毛、羽绒及其制品；人造花；人发制品", "Prepared feathers and down and articles made of feathers or of down; artificial flowers; articles of human hair"),
 "68": ("石料、石膏、水泥、石棉、云母及类似材料的制品", "Articles of stone, plaster, cement, asbestos, mica or similar materials"),
 "69": ("陶瓷产品", "Ceramic products"),
 "70": ("玻璃及其制品", "Glass and glassware"),
 "71": ("天然或养殖珍珠、宝石或半宝石、贵金属、包贵金属及其制品；仿首饰；硬币", "Natural or cultured pearls, precious or semi-precious stones, precious metals, metals clad with precious metal, and articles thereof; imitation jewellery; coin"),
 "72": ("钢铁", "Iron and steel"),
 "73": ("钢铁制品", "Articles of iron or steel"),
 "74": ("铜及其制品", "Copper and articles thereof"),
 "75": ("镍及其制品", "Nickel and articles thereof"),
 "76": ("铝及其制品", "Aluminium and articles thereof"),
 "78": ("铅及其制品", "Lead and articles thereof"),
 "79": ("锌及其制品", "Zinc and articles thereof"),
 "80": ("锡及其制品", "Tin and articles thereof"),
 "81": ("其他贱金属、金属陶瓷及其制品", "Other base metals; cermets; articles thereof"),
 "82": ("贱金属工具、器具、利口器、餐匙、餐叉及其零件", "Tools, implements, cutlery, spoons and forks, of base metal; parts thereof"),
 "83": ("贱金属杂项制品", "Miscellaneous articles of base metal"),
 "84": ("核反应堆、锅炉、机器、机械器具及其零件", "Nuclear reactors, boilers, machinery and mechanical appliances; parts thereof"),
 "85": ("电机、电气设备及其零件；录音机及放声机、电视图像及声音的录制和重放设备及其零件、附件", "Electrical machinery and equipment and parts thereof; sound recorders and reproducers, television image and sound recorders and reproducers, and parts and accessories"),
 "86": ("铁道及电车道机车、车辆及其零件；轨道固定装置及其零件；机械交通信号设备", "Railway or tramway locomotives, rolling stock and parts thereof; railway or tramway track fixtures and fittings; mechanical traffic signalling equipment"),
 "87": ("车辆及其零件、附件（铁道及电车道车辆除外）", "Vehicles other than railway or tramway rolling stock, and parts and accessories thereof"),
 "88": ("航空器、航天器及其零件", "Aircraft, spacecraft, and parts thereof"),
 "89": ("船舶及浮动结构体", "Ships, boats and floating structures"),
 "90": ("光学、照相、电影、计量、检验、医疗或外科用仪器及设备、精密仪器及设备；零件及附件", "Optical, photographic, cinematographic, measuring, checking, precision, medical or surgical instruments and apparatus; parts and accessories"),
 "91": ("钟表及其零件", "Clocks and watches and parts thereof"),
 "92": ("乐器及其零件、附件", "Musical instruments; parts and accessories of such articles"),
 "93": ("武器、弹药及其零件、附件", "Arms and ammunition; parts and accessories thereof"),
 "94": ("家具；寝具、褥垫、弹簧床垫、软坐垫及类似填充制品；未列名灯具及照明装置；发光标志；活动房屋", "Furniture; bedding, mattresses, mattress supports, cushions and similar stuffed furnishings; luminaires and lighting fittings n.e.s.; illuminated signs; prefabricated buildings"),
 "95": ("玩具、游戏品、运动用品及其零件、附件", "Toys, games and sports requisites; parts and accessories thereof"),
 "96": ("杂项制品", "Miscellaneous manufactured articles"),
 "97": ("艺术品、收藏品及古物", "Works of art, collectors' pieces and antiques"),
 # 98 是美国 HTS 特有的「特殊分类规定」章（HS 本体无此章），中文为参考译名
 "98": ("特殊分类规定（美国 HTS 特有）", "Special classification provisions"),
}


def digits(s):
    return re.sub(r"\D", "", s or "")


def clean(s):
    """去掉祖先链里残留的冒号与空白 —— 'Live horses, asses, mules and hinnies:' → 干净品名"""
    return re.sub(r"\s+", " ", (s or "").replace(":", " ").strip()).strip()


def main():
    ap = argparse.ArgumentParser(description="生成 TariffLens 按类别浏览索引")
    ap.add_argument("--out", default=DEFAULT_OUT, help="产物目录（默认 data）")
    ap.add_argument("--tag", default=None, help="HTS 版本 tag，默认从 index 分片读取")
    a = ap.parse_args()

    out = a.out
    idx_path = None
    for p in sorted(glob.glob(os.path.join(out, "hts-*-index.json.gz"))):
        idx_path = p
    if not idx_path:
        sys.exit(f"找不到 {out}/hts-*-index.json.gz —— 先跑 fetch_tariff_data.py hts")
    tag = a.tag or json.loads(gzip.open(idx_path, "rt", encoding="utf-8").read()).get("tag", "2026rev9")

    chapters = []
    for p in sorted(glob.glob(os.path.join(out, f"hts-{tag}-ch[0-9][0-9].json.gz"))):
        m = re.search(r"-ch(\d\d)\.json", p)
        if not m:
            continue
        ch = m.group(1)
        if ch == "99":
            continue
        rows = json.loads(gzip.open(p, "rt", encoding="utf-8").read())["rows"]
        heads, seen = [], {}
        for r in rows:
            d = digits(r["h"])
            if len(d) < 4:
                continue
            h4 = d[:4]
            if h4 not in seen:
                # 4 位 heading 的名字不在税则行上，取该 heading 下第一行的祖先链首段
                anc = (r.get("p") or [])
                name = clean(anc[0]) if anc else clean(r.get("d"))
                if not name:
                    name = clean(r.get("d"))
                seen[h4] = [h4, name[:90], 0]
                heads.append(seen[h4])
            seen[h4][2] += 1
        zh, en = CH_TITLES.get(ch, ("", ""))
        chapters.append({"ch": ch, "zh": zh, "en": en, "n": len(rows), "heads": heads})

    chapters.sort(key=lambda c: c["ch"])
    doc = {
        "tag": tag,
        "generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d"),
        "note": "章名中文为参考译名；正式品名以 HTS 英文原文为准。第 77 章空缺。",
        "chapters": chapters,
    }
    dst = os.path.join(out, f"hts-{tag}-browse.json.gz")
    with gzip.open(dst, "wt", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))

    nheads = sum(len(c["heads"]) for c in chapters)
    print(f"✅ 写出 {dst}")
    print(f"   章 {len(chapters)} 个 · 4 位 heading {nheads} 条 · "
          f"{os.path.getsize(dst)/1024:.1f} KB (gzip)")
    missing = [c["ch"] for c in chapters if not c["zh"]]
    if missing:
        print(f"   ⚠ 缺中文章名: {missing}")


if __name__ == "__main__":
    main()
