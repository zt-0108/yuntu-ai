from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "data"
FONT_REGULAR = Path(r"C:\Windows\Fonts\Deng.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\Dengb.ttf")

COLORS = {
    "苏州": colors.HexColor("#315C55"),
    "扬州": colors.HexColor("#75523A"),
    "杭州": colors.HexColor("#345C78"),
    "南京": colors.HexColor("#7A3545"),
}


GUIDES = {
    "苏州": {
        "subtitle": "园林、古城水巷与现代湖区的三日慢游",
        "intro": (
            "苏州适合把古典园林、历史街区和现代滨水空间组合起来游览。古城内景点密集，"
            "步行和轨道交通通常比自驾更省心；平江路、拙政园、苏州博物馆可以串成一条步行线，"
            "虎丘、山塘街适合安排在另一个半日，金鸡湖则适合傍晚到夜间。"
        ),
        "highlights": [
            ("拙政园", "姑苏区东北街", "2-3 小时", "以水景和疏朗自然的空间见长。建议预约较早时段，重点观察门洞、花窗、廊桥与水面形成的借景关系。"),
            ("苏州博物馆", "姑苏区东北街", "2-3 小时", "适合与拙政园连游。建筑、馆藏和庭院共同呈现苏州历史与江南审美，热门日期通常需要提前预约。"),
            ("平江历史街区", "姑苏区平江路一带", "2-3 小时", "保留河街相邻的古城格局，适合慢走支巷、看小桥水巷，并把小吃和茶馆安排在途中。"),
            ("虎丘", "姑苏区虎丘山门内", "2-3 小时", "自然山体与历史遗迹结合，适合和山塘街组成半日线路。节假日优先乘轨道交通或公交。"),
            ("留园", "姑苏区留园路", "1.5-2.5 小时", "空间层次紧凑，建筑、山石和庭院转换丰富，适合与拙政园进行不同造园风格的对照游览。"),
            ("金鸡湖", "苏州工业园区", "2-4 小时", "现代城市滨水空间，适合日落前抵达，沿湖散步并在周边商圈用餐。"),
        ],
        "food": [
            "苏式汤面：可按红汤、白汤及浇头选择，适合作为早餐或简餐。",
            "松鼠鳜鱼与响油鳝糊：经典苏帮菜，口味偏甜鲜，建议多人分享。",
            "生煎、汤包、海棠糕、梅花糕：适合古城步行途中少量分次品尝。",
            "碧螺春与苏式茶点：适合安排一次茶馆休息，避免行程全部围绕打卡。",
        ],
        "stay": [
            "观前街/平江路周边：古城体验最好，步行方便，但节假日人流集中。",
            "苏州站/北寺塔周边：换乘方便，适合高铁抵达和短住。",
            "金鸡湖周边：酒店和商业设施较新，适合偏好现代城市环境的游客。",
        ],
        "days": [
            ("第一天 - 古典园林与水巷", "上午拙政园；中午园林路周边简餐；下午苏州博物馆；傍晚沿平江路慢走至观前街。"),
            ("第二天 - 虎丘与山塘", "上午虎丘；下午从山塘街向古城方向游览；晚上可听一场评弹或安排苏帮菜。"),
            ("第三天 - 园林对照与现代湖区", "上午留园；下午休息后前往金鸡湖；日落前后沿湖散步并在湖区用餐。"),
        ],
        "tips": [
            "地铁 6 号线串联虎丘、苏州博物馆、拙政园、狮子林、平江路、网师园和金鸡湖等区域。",
            "古城热门景点之间距离不远，但石板路和园林步行量较大，建议穿防滑舒适鞋。",
            "园林、博物馆预约规则可能调整，出发前通过景区或场馆官方渠道确认。",
            "春季花事和夏季荷景有特色；梅雨季需准备雨具，雨天园林地面较滑。",
        ],
        "sources": [
            ("苏州市人民政府：古城旅游交通出行攻略", "https://www.suzhou.gov.cn/szsrmzf/mszx/202505/0ad6ad26c7b54888b651a6259c4dfc2f.shtml"),
            ("苏州市园林和绿化管理局：拙政园", "https://ylj.suzhou.gov.cn/szsylj/sjyc/201905/c1df393edc8745abb20e8a9bd5525782.shtml"),
            ("苏州市人民政府：平江历史街区", "https://www.suzhou.gov.cn/gsbdbwlyjc/yshi/202008/12875852fc0845afa5534cc7b29c5b19.shtml"),
            ("苏州市文化广电和旅游局：A级景区名录", "https://wglj.suzhou.gov.cn/szwhgdhlyj/Ajqq/list_tt.shtml"),
        ],
    },
    "扬州": {
        "subtitle": "瘦西湖、盐商园林与大运河文化的三日慢游",
        "intro": (
            "扬州的核心体验集中在瘦西湖、古城园林和大运河文化三条线。城市尺度适合慢游，"
            "第一天可沿瘦西湖和蜀冈游览，第二天深入个园、东关街与何园，第三天前往中国大运河博物馆。"
            "早茶和淮扬菜本身就是行程的重要组成部分，建议预留完整用餐时间。"
        ),
        "highlights": [
            ("瘦西湖", "邗江区大虹桥路一带", "3-5 小时", "湖上园林与桥、亭、花木相互借景，五亭桥、白塔、二十四桥是经典节点。春季花事期间建议早到。"),
            ("大明寺", "蜀冈中峰", "1.5-2.5 小时", "可与瘦西湖北段衔接，适合了解鉴真文化，并从高处观察蜀冈与城市景观。"),
            ("个园", "广陵区东关街", "1.5-2 小时", "以竹景和四季假山闻名，是理解扬州盐商园林和叠石艺术的重要地点。"),
            ("何园", "广陵区徐凝门街", "1.5-2 小时", "晚清住宅园林代表，复道回廊和中西结合的建筑细节值得慢看。"),
            ("东关街历史街区", "广陵区东关街", "2-3 小时", "老字号、传统工艺和街巷生活集中，建议离开主街进入附近支巷，减少单纯商业化打卡。"),
            ("扬州中国大运河博物馆", "广陵区运河三湾", "3-4 小时", "从历史、工程、城市和生活多个角度理解大运河，馆体量较大，通常需要提前预约。"),
        ],
        "food": [
            "扬州早茶：烫干丝、蟹黄汤包、三丁包、千层油糕可组合品尝，热门茶社建议错峰。",
            "扬州炒饭：注意不同餐馆做法差异较大，可作为简餐而非唯一代表菜。",
            "狮子头、大煮干丝、软兜长鱼：适合多人共享的淮扬菜代表。",
            "藕粉圆子、桂花糖藕：适合餐后或下午茶，整体口味偏清甜。",
        ],
        "stay": [
            "瘦西湖/虹桥坊周边：便于早起入园和体验早茶，适合首次到访。",
            "东关街/个园周边：古城氛围浓，步行可达园林和老街。",
            "文昌阁周边：商业、餐饮和公共交通更均衡。",
        ],
        "days": [
            ("第一天 - 湖上园林", "早茶后进入瘦西湖，自南向北游览；下午衔接大明寺；晚上回到虹桥坊或文昌阁用餐。"),
            ("第二天 - 盐商园林与古城", "上午个园；中午东关街周边；下午何园和附近老城支巷；晚上品尝淮扬菜。"),
            ("第三天 - 大运河主题", "上午至下午参观扬州中国大运河博物馆；余下时间在运河三湾散步，行程结束前安排一次扬州早茶或茶点。"),
        ],
        "tips": [
            "瘦西湖面积较大，与大明寺连游时步行量明显，亲子和长者可减少支线。",
            "园林空间适合慢看，不建议在一天内压缩瘦西湖、个园和何园全部景点。",
            "中国大运河博物馆预约和入馆要求以官方平台为准。",
            "所谓烟花三月通常是热门季节，住宿与早茶排队压力较大，可选择工作日。",
        ],
        "sources": [
            ("扬州瘦西湖风景区官网", "https://shouxihu.com/home.php"),
            ("扬州市何园管理处官网", "https://www.he-garden.net/"),
            ("文化和旅游部：扬州智慧旅游服务", "https://www.mct.gov.cn/whzx/qgwhxxlb/js/202006/t20200605_854142.htm"),
            ("江苏省人民政府：扬州文旅改造项目", "https://www.jiangsu.gov.cn/art/2024/5/1/art_84324_11233441.html"),
        ],
    },
    "杭州": {
        "subtitle": "西湖山水、宋韵街区与世界遗产的三日游",
        "intro": (
            "杭州不宜只安排环西湖打卡。更舒适的组合是用一天走西湖经典线，一天进入灵隐和西湖西侧山林，"
            "再用一天在西溪湿地、良渚或大运河主题中择一。西湖范围大，步行、公交、地铁和短程骑行应灵活组合。"
        ),
        "highlights": [
            ("西湖核心景区", "上城区/西湖区", "半天至 1 天", "断桥、白堤、孤山、苏堤、花港观鱼和雷峰塔分布较广，应按体力选段，不必一次走完全湖。"),
            ("灵隐飞来峰景区", "西湖区灵隐路", "3-4 小时", "山林、石刻与寺院文化集中，热门时段交通和排队压力较大，宜早出发并确认预约购票规则。"),
            ("西溪国家湿地公园", "西湖区天目山路一带", "3-5 小时", "湿地水网、村落文化和生态体验结合，可根据季节选择步行或水上线路。"),
            ("良渚古城遗址公园与良渚博物院", "余杭区", "1 天", "适合历史文化和亲子研学，遗址公园尺度大，建议与博物院组合并预留交通时间。"),
            ("河坊街与南宋御街", "上城区", "2-3 小时", "适合了解南宋以来的城市街巷和传统商业，可与胡庆余堂、鼓楼一带串联。"),
            ("京杭大运河杭州段", "拱墅区", "3-4 小时", "可围绕拱宸桥、桥西历史街区和运河沿岸博物馆群安排半日。"),
        ],
        "food": [
            "片儿川、葱包桧、定胜糕：适合早餐或步行途中补充。",
            "西湖醋鱼、龙井虾仁、东坡肉：传统杭帮菜代表，建议多人共享并按个人口味点单。",
            "知味小笼、猫耳朵：适合简餐，热门门店可错峰。",
            "龙井茶：可在正规茶馆体验，购买茶叶时注意明码标价并理性消费。",
        ],
        "stay": [
            "湖滨/龙翔桥周边：首次到访最方便，夜间活动丰富，但住宿价格通常较高。",
            "武林广场/凤起路周边：地铁换乘和餐饮便利，前往西湖也较近。",
            "黄龙/西湖北侧：适合计划灵隐、西溪路线的游客。",
        ],
        "days": [
            ("第一天 - 西湖经典", "上午断桥、白堤和孤山；下午按体力选择苏堤南段、花港观鱼或雷峰塔；晚上湖滨散步。"),
            ("第二天 - 山林与宋韵", "早上灵隐飞来峰；下午回城游览河坊街、南宋御街和鼓楼一带；晚上品尝杭帮菜。"),
            ("第三天 - 主题分支", "生态偏好选择西溪湿地；历史研学选择良渚；城市文化偏好选择拱宸桥与运河博物馆群。"),
        ],
        "tips": [
            "西湖景区节假日交通压力大，优先使用地铁接驳、公交和步行。",
            "灵隐、西溪、良渚并不在同一紧凑片区，不建议一天内强行串联。",
            "博物馆、遗址公园和寺院的预约规则不同，须分别确认。",
            "春秋适合步行；盛夏注意高温和雷雨，冬季山路清晨可能湿滑。",
        ],
        "sources": [
            ("杭州市文化广电旅游局：10 条文化旅游精品线路", "https://wgly.hangzhou.gov.cn/module/download/downfile.jsp?classid=0&filename=c3ccb4250d3143a09047ee20fbe1170c.pdf"),
            ("杭州市文化设施专项规划：西湖、大运河、良渚、西溪等文旅核心", "https://wgly.hangzhou.gov.cn/module/download/downfile.jsp?classid=0&filename=dbc1b08ef03e4e2ebe5477d78df83d14.pdf"),
        ],
    },
    "南京": {
        "subtitle": "钟山、博物馆与秦淮古城的三日历史文化游",
        "intro": (
            "南京的核心线路可以分成钟山风景区、城东博物馆与民国建筑、秦淮古城三组。"
            "钟山内部范围大，适合单独留出一天；南京博物院和总统府等场馆应提前预约；"
            "夫子庙、老门东更适合傍晚进入，把夜景和晚餐放在同一区域。"
        ),
        "highlights": [
            ("中山陵", "玄武区钟山风景区", "2-3 小时", "陵寝建筑轴线与近代历史主题鲜明，通常实行预约参观。可与音乐台、明孝陵或灵谷景区组合。"),
            ("明孝陵", "玄武区钟山南麓", "3-4 小时", "世界文化遗产，神道、陵宫、梅花山等分布较广。秋季石象路和早春梅花山各有特色。"),
            ("南京博物院", "玄武区中山东路", "3-4 小时", "馆藏与展陈覆盖江苏历史、艺术和民俗，体量较大，热门日期需要提前预约。"),
            ("总统府", "玄武区长江路", "2-3 小时", "建筑群承载太平天国、晚清与民国历史，可与长江路文化街区联游。"),
            ("夫子庙 - 秦淮风光带", "秦淮区", "3-4 小时", "可串联夫子庙、科举博物馆、白鹭洲、中华门和老门东，夜间氛围更浓。"),
            ("玄武湖与南京城墙", "玄武区", "2-4 小时", "适合城市漫步和轻松行程，可根据开放情况选择台城等城墙段观察古城格局。"),
        ],
        "food": [
            "鸭血粉丝汤、盐水鸭：南京代表性风味，注意不同门店咸度和口味差异。",
            "牛肉锅贴、皮肚面、小馄饨：适合早餐或简餐。",
            "桂花糖芋苗、赤豆元宵：偏甜的传统小吃，适合少量尝试。",
            "金陵菜：可选择炖生敲、炖菜核等传统菜，多人同行更方便分享。",
        ],
        "stay": [
            "新街口周边：交通、商业和餐饮最集中，适合首次到访。",
            "夫子庙/老门东周边：夜游方便，但节假日较嘈杂。",
            "鼓楼/玄武门周边：适合玄武湖、城墙和高校人文路线。",
        ],
        "days": [
            ("第一天 - 钟山历史轴线", "上午明孝陵神道与陵宫；下午中山陵、音乐台或灵谷景区择二；傍晚返回市区。"),
            ("第二天 - 博物馆与长江路", "上午南京博物院；下午总统府和长江路文化街区；晚上新街口或附近街区用餐。"),
            ("第三天 - 城墙与秦淮", "上午玄武湖和城墙；下午中华门、老门东；傍晚至夜间游览夫子庙秦淮河一带。"),
        ],
        "tips": [
            "钟山景区内部距离长，可利用观光车连接明孝陵、中山陵、音乐台和灵谷等节点。",
            "中山陵、南京博物院等预约要求可能调整，务必通过官方平台确认。",
            "夫子庙核心区夜间人流大，亲子和长者可提前到达、错峰离开。",
            "南京夏季湿热，钟山步行注意补水；秋季和早春适合自然与历史结合的线路。",
        ],
        "sources": [
            ("南京市人民政府：南京 5A 景区主要景点", "https://www.nanjing.gov.cn/hdjl/hygq/202208/t20220829_3684096.html"),
            ("南京市中山陵园管理局：明孝陵景区", "https://zschina.nanjing.gov.cn/fjms/jqjd/mxljq/"),
            ("南京市中山陵园管理局：钟山游览与预约提示", "https://zschina.nanjing.gov.cn/lyzx/202606/t20260618_5862979.html"),
            ("南京市人民政府：南京春季旅游线路", "https://www.nanjing.gov.cn/zzb/ywdt/msxx/202302/t20230213_5125935.html"),
        ],
    },
}


def _register_fonts() -> None:
    if not FONT_REGULAR.exists() or not FONT_BOLD.exists():
        raise FileNotFoundError("未找到 Windows 等线字体，无法生成中文 PDF。")
    pdfmetrics.registerFont(TTFont("Yuntu", str(FONT_REGULAR)))
    pdfmetrics.registerFont(TTFont("Yuntu-Bold", str(FONT_BOLD)))


def _styles(accent: colors.Color) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="Yuntu-Bold",
            fontSize=27,
            leading=36,
            textColor=accent,
            alignment=TA_CENTER,
            spaceAfter=10 * mm,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontName="Yuntu",
            fontSize=13,
            leading=22,
            textColor=colors.HexColor("#50605D"),
            alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Yuntu-Bold",
            fontSize=18,
            leading=25,
            textColor=accent,
            spaceBefore=6 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Yuntu-Bold",
            fontSize=12.5,
            leading=18,
            textColor=colors.HexColor("#263B37"),
            spaceBefore=3 * mm,
            spaceAfter=1.5 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Yuntu",
            fontSize=10.5,
            leading=17,
            textColor=colors.HexColor("#26302E"),
            spaceAfter=2.5 * mm,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="Yuntu",
            fontSize=10,
            leading=16,
            leftIndent=5 * mm,
            firstLineIndent=-3 * mm,
            bulletIndent=1 * mm,
            spaceAfter=1.5 * mm,
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Yuntu",
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#53615E"),
            wordWrap="CJK",
        ),
        "source": ParagraphStyle(
            "Source",
            parent=base["BodyText"],
            fontName="Yuntu",
            fontSize=8.5,
            leading=13,
            leftIndent=4 * mm,
            firstLineIndent=-3 * mm,
            textColor=colors.HexColor("#40514D"),
            wordWrap="CJK",
            spaceAfter=1.5 * mm,
        ),
    }


def _page_decorator(city: str, accent: colors.Color):
    def draw(canvas, doc) -> None:
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(accent)
        canvas.rect(0, height - 9 * mm, width, 9 * mm, fill=1, stroke=0)
        canvas.setFont("Yuntu", 8)
        canvas.setFillColor(colors.HexColor("#65716F"))
        canvas.drawString(18 * mm, 10 * mm, f"云途 AI 本地知识库 - {city}旅行攻略")
        canvas.drawRightString(width - 18 * mm, 10 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    return draw


def _bullet(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(f"• {text}", style)


def build_guide(city: str, guide: dict) -> Path:
    accent = COLORS[city]
    styles = _styles(accent)
    path = OUTPUT_DIR / f"{city}_guide.pdf"
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"2026 {city}深度游玩全攻略",
        author="云途 AI 本地知识库",
        subject=f"{city}旅行规划与 RAG 本地知识",
    )

    story = [
        Spacer(1, 34 * mm),
        Paragraph(f"2026 {city}深度游玩全攻略", styles["cover_title"]),
        Paragraph(guide["subtitle"], styles["cover_subtitle"]),
        Spacer(1, 18 * mm),
        Table(
            [["建议天数", "3 天"], ["适合人群", "文化旅行、城市漫步、亲子与摄影"], ["资料更新", "2026-08-06"]],
            colWidths=[35 * mm, 95 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Yuntu"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("TEXTCOLOR", (0, 0), (0, -1), accent),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF3F1")),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E1DE")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        ),
        Spacer(1, 18 * mm),
        Paragraph("内容定位", styles["h2"]),
        Paragraph(
            "本攻略用于行程规划和知识库检索，不替代景区当日公告。票价、开放时间、预约、交通管制和演出安排可能变化，请在出发前通过官方渠道复核。",
            styles["body"],
        ),
        PageBreak(),
        Paragraph("1. 目的地简介", styles["h1"]),
        Paragraph(guide["intro"], styles["body"]),
        Paragraph("2. 核心景点推荐", styles["h1"]),
    ]

    for index, (name, location, duration, description) in enumerate(guide["highlights"], 1):
        story.append(
            KeepTogether(
                [
                    Paragraph(f"2.{index} {name}", styles["h2"]),
                    Paragraph(f"<b>区域：</b>{location}　<b>建议时长：</b>{duration}", styles["small"]),
                    Paragraph(description, styles["body"]),
                ]
            )
        )

    story.extend([Paragraph("3. 特色餐饮", styles["h1"])] + [_bullet(item, styles["bullet"]) for item in guide["food"]])
    story.append(
        KeepTogether(
            [Paragraph("4. 住宿区域建议", styles["h1"])]
            + [_bullet(item, styles["bullet"]) for item in guide["stay"]]
        )
    )
    story.append(Paragraph("5. 经典三日行程参考", styles["h1"]))
    for title, route in guide["days"]:
        story.append(KeepTogether([Paragraph(title, styles["h2"]), Paragraph(route, styles["body"])]))

    story.extend([Paragraph("6. 交通、预约与季节提示", styles["h1"])] + [_bullet(item, styles["bullet"]) for item in guide["tips"]])
    story.append(Paragraph("7. 预算使用说明", styles["h1"]))
    story.append(
        Paragraph(
            "住宿、餐饮和门票价格受日期、房型、套餐与促销影响较大，本攻略不写死实时价格。规划预算时可先按住宿 40%-50%、餐饮 20%-25%、市内交通 10%-15%、门票与体验 15%-25% 分配，再根据实际预订结果调整。",
            styles["body"],
        )
    )
    story.append(Paragraph("8. 资料来源与时效", styles["h1"]))
    story.append(
        Paragraph(
            "以下资料用于核对景点定位、文化背景和线路关系，整理日期为 2026-08-06。易变信息以景区、场馆和交通部门最新公告为准。",
            styles["small"],
        )
    )
    for label, url in guide["sources"]:
        story.append(Paragraph(f'• <link href="{url}" color="#315C55">{label}</link>', styles["source"]))

    decorator = _page_decorator(city, accent)
    doc.build(story, onFirstPage=decorator, onLaterPages=decorator)
    return path


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _register_fonts()
    for city, guide in GUIDES.items():
        path = build_guide(city, guide)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
