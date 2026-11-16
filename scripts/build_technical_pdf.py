"""Build the review draft with ReportLab; use a Chinese Unicode font."""
from pathlib import Path
import json,os
from html import escape
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Table,TableStyle,Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing,Rect,String,Line,Polygon
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pdf/TraceScholar-技术说明-审阅稿.pdf'
FONT=os.getenv('TRACESCHOLAR_CJK_FONT','/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
pdfmetrics.registerFont(TTFont('CJK',FONT))
C=colors.HexColor
styles={
 'title':ParagraphStyle('title',fontName='CJK',fontSize=27,leading=40,textColor=C('#292b58'),spaceAfter=22),
 'h1':ParagraphStyle('h1',fontName='CJK',fontSize=20,leading=29,textColor=C('#25294b'),spaceAfter=18),
 'h2':ParagraphStyle('h2',fontName='CJK',fontSize=12,leading=19,textColor=C('#5550ae'),spaceBefore=14,spaceAfter=7),
 'body':ParagraphStyle('body',fontName='CJK',fontSize=10.2,leading=18,textColor=C('#344054'),spaceAfter=9,wordWrap='CJK'),
 'small':ParagraphStyle('small',fontName='CJK',fontSize=8.4,leading=14,textColor=C('#657084'),spaceAfter=7,wordWrap='CJK')}
story=[]
def p(text,kind='body'):return Paragraph(escape(text).replace('\n','<br/>'),styles[kind])
def para(text,kind='body'):story.append(p(text,kind))
def heading(n,title):para(f'{n:02d}  {title}','h1')
def sec(title,text):para(title,'h2');para(text)
def new():story.append(PageBreak())
def rows(headers,data,widths):
 t=Table([[p(x,'small') for x in row] for row in [headers]+data],colWidths=widths,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),C('#eeedfc')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.7,C('#b7b5db')),('LINEBELOW',(0,1),(-1,-1),.3,C('#e1e5ec')),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),7)]));story.append(t)
para('TRACESCHOLAR / 2026.11.16','small')
para('可信科研助手 Agent\n技术说明 · 审阅稿','title')
para('让研究结论回到可检查的论文、版本和原始页码。')
story.append(Spacer(1,28))
rows(['项目项','填写与状态'],[['参赛姓名 / 学校 / 团队','待参赛者填写，与报名信息核对'],['项目定位','通用可信科研文献助手，以组委会官方论文集验证'],['本稿用途','本地实现与实测说明；尚未确认线上最终版本与提交信息'],['视觉能力','扫描文本 OCR 已有；图片理解、扫描表格、公式 LaTeX 按用户决定后续接入']], [128,377])
sec('要解决的问题','科研读者需要核对版本、找到细粒度信息、阅读跨语言文献并比较多篇结论。只生成流畅文字不足以支持研究：结论需要可定位的来源，资料缺失应说明不足。')
sec('本轮交付','独立研究工作区连接图表、版本、翻译、工具 Agent、检索追踪、图谱综述和后台任务。代码、固定题库、评测 JSON、测试指南与提交清单共同记录实现和边界。')
para('本稿不代表赛事官方验收。正式提交前需补身份信息、检查演示地址和评审凭证，并完成跨设备及部署验收。','small')
new();heading(1,'架构与证据链')
d=Drawing(505,192)
boxes=[(10,120,145,'论文输入与版本'),(180,120,145,'解析 / OCR / 索引'),(350,120,145,'检索与工具 Agent'),(10,30,145,'原版阅读与定位'),(180,30,145,'带引用回答 / 综述'),(350,30,145,'日志、评测与导出')]
for x,y,w,label in boxes:
 d.add(Rect(x,y,w,44,rx=7,ry=7,fillColor=C('#f1f0fd'),strokeColor=C('#cac7e7')));d.add(String(x+w/2,y+18,label,fontName='CJK',fontSize=10,textAnchor='middle',fillColor=C('#38345f')))
for a,b,c,e in [(155,142,180,142),(325,142,350,142),(422,120,422,74),(350,52,325,52),(180,52,155,52)]:d.add(Line(a,b,c,e,strokeColor=C('#8984bc'),strokeWidth=1.5))
story.append(d)
sec('技术选型','后端 FastAPI / Python，PDF 用 PyMuPDF；Linux 使用 Tesseract，macOS 可使用 Vision。前端为中文原生 HTML/CSS/JavaScript，无前端构建要求。matplotlib 负责受控 CSV 绘图。文本生成使用已配置的 DeepSeek 兼容接口。')
sec('统一来源','paper_id 表示具体文件记录，work_id 聚合同一研究工作，版本、章节、页码和片段随检索与回答传递。图表额外保留 bbox。回答引用标签映射到本地证据；可从证据返回原始页面。')
sec('检索方法','BM25 为主，另有 TF-IDF 稀疏余弦与排名融合。中英混杂问题使用可审计术语桥接与符号归一化，例如 β1/beta1。没有接入稠密 embedding 或神经重排，不以此命名现有算法。')
sec('引用与事实边界','系统检查引用是否对应已返回的来源，多篇比较要求每篇来源覆盖。引用可追溯不等于已经证明语义蕴含，关键结论仍需核对；检索范围不足时不认证全球新颖性。')
new();heading(2,'入库、版本与任务工程')
sec('导入和去重','检查格式、体积、页数与加密状态；SHA-256 识别完全重复。正文五词片段哈希重合率结合 arXiv/DOI 关联版本，长文档最多采样 20 页。用户可取消、保留两版或确认替换。被替换记录归档，保留旧引用与原文件。')
sec('正文差异','同 work_id 的两个记录按规范化五行片段比较，显示章节增删与原文来源，可下载报告。它对排版变化敏感，不能自动认定某科学结论已经改变。')
sec('扫描文本','逐页 OCR 保存成功文字、失败页与真实进度，完成后重建章节和检索块。第五轮官方 15 页扫描件在 macOS Vision 完成 15/15 页；这证明文本链路，不证明扫描表格和图形语义恢复。')
sec('可继续的本地任务','解析、翻译与批量导入持久保存任务和已完成步骤，进程中断后可继续。批量最多 20 文件，逐文件处理冲突；有保留两版、取消和暂存清理。已有后台任务时阻止删除/替换，避免数据竞争。')
sec('资源与部署','常规后台任务限制 2 个，OCR 同时 1 个，工具 Agent 同时 1 个；PDF 按需分析。单实例单进程依赖本地锁和磁盘，线程队列不是分布式系统。免费平台休眠时轮询停止；磁盘被清空时无法恢复任务。')
rows(['验证对象','本地结果','解释'],[['官方 20 篇 + 引用图','20 节点 / 75 条匹配边','边保留引用段落，不是人工逐条审定'],['541 页教材','1638 块；约 2.5 秒基础解析','深页查询命中 382-386 页'],['独立评测进程','约 201 MiB 峰值（macOS）','包含前述论文与教材；不是云端保证']], [122,165,218])
new();heading(3,'图表结构与阅读翻译')
sec('原生表格提取','常规表格使用 PDF 单元格提取；仅有横线的表格按横线边界、原生文字坐标和行中心聚类恢复列。多级表头组合显示，合并范围单列，未知不补零，上标保留指数含义。该几何方法不替代通用视觉模型。')
rows(['Table 2 模型','EN-DE BLEU','EN-FR BLEU'],[['Transformer base','27.3','38.1'],['Transformer big','28.4','41.8']], [255,125,125])
para('训练成本合并跨列，不重复为独立测量。表格/正文同时存在 41.8 与 41.0 时，真实回答明确提示原文差异；不擅自“修正”论文。','small')
sec('图片和公式','保留图注邻近原版区域、嵌入图片位置与完整原页链接。图注邻近区域仅为候选；公式返回原文、位置和截图，没有伪装生成 LaTeX。机构文字亦明确为待核对候选。')
sec('阅读往返','原版 PDF 逐页渲染，支持整页适应、缩放和带编号章节导航。原生文字可按选区或证据片段查坐标高亮，翻页清理旧区域。正文编号连接参考文献条目、参考文献原页与返回正文页。')
sec('翻译','段落翻译先验证本页来源；全文任务按页保存、缓存、重试和导出。双语文本按滚动比例联动，并非逐句语义对齐。真实 DeepSeek 单页翻译已成功；扫描页无词坐标、复杂跨页参考文献仍有局限。')
new();heading(4,'受控模型工具与研究闭环')
sec('真实 Function Calling','规划请求提供 retrieve、inspect_page、citation_graph、compare_versions 与可选 search_public。每次最多 1-6 次工具调用，参数检查、所选论文权限、重复指纹检测、结果大小限制和运行记录由程序执行。仅公开搜索摘要不能冒充本地全文证据。')
sec('真实调用结果','DeepSeek 选择 inspect_page 检查官方第 8 页 Table 2，最终引用本地来源回答：base EN-DE BLEU 27.3，big 28.4，相差 1.1。浏览器同题又完成 inspect_page 和 retrieve。这个小样本验证工具链可运行，不保证任意任务规划可靠。')
sec('论文发现与反馈','arXiv 题名检索和确认下载只访问固定 HTTPS 主机，并限制体积和重定向。真实搜索返回 5 项，v1 下载入库成功。可添加主题轮询、从摘要/本地全文提取 GitHub 仓库线索，推荐反馈影响共享演示库结果；代码质量未核验。')
sec('图谱、综述和方向核对','仅在参考文献区域匹配库内题名并保留边来源，计算选定子图 PageRank。以主题组织带引用综述和 Future Work 时间线；按支持、部分支持、反例、证据不足检查方向，明确只限已选论文。arXiv 月份不是首次发表日期。')
sec('写作和可视化','综述提纲区分事实与待验证计划。用户编辑节点/边生成 SVG 预览和 Mermaid/Graphviz 脚本；它描述拟议方法，不代表实验完成。CSV 支持折线、柱状、散点、雷达、3D 雷达、3D 散点和表格；统计由固定程序计算，不运行模型代码。')
new();heading(5,'测试、失败与修正')
rows(['检查','结果','局限'],[['后端 / 前端','146 / 16 项通过','选定场景回归，非官方全功能认证'],['Transformer 固定检索题','20 可回答题页码命中@1 100%；要点覆盖 94%','开发集；2 负例误召回 0%'],['三文档扩展集','范围内命中@6 87.5%；全库 75%','2 比较题使用模拟生成'],['六道细粒度开发题','页码 6/6；字符串要点 18/18','作者脚注初答不足，修正后真实复测'],['真实模型和网络','工具、表格问答、单页翻译、搜索、下载成功','单次检查，不是长期 SLA']], [122,205,178])
sec('保留初始失败','作者机构题第一轮只取到署名，模型说明缺少脚注。加入 work performed 脚注检索后，真实复测区分 Toronto 署名机构与 Google Brain 工作机构。初始与复测记录分别保留，没有把初始失败改写为全通过。')
sec('表格和引用修正','实际官方表格暴露了错列与指数拼接，增加横线几何提取和上标标识后核对 base/big BLEU 与合并成本。浏览器发现最后参考文献吸收附录，已限制编号参考文献边界并添加回归。')
sec('界面与安全','浏览器核对版本报告、表格、高亮清理、正文第 3 页与文献第 10 页往返、架构图和真实工具结果；390px 视口无整页横向溢出。模型表格文本转义，CSV 防公式注入，生产认证保护任务和运行历史。')
new();heading(6,'复现与交付验收')
sec('本地启动','Python 3.10+；在 backend 建立虚拟环境并安装 requirements.txt。以 uvicorn app.main:app --env-file ../.env --port 8000 启动。密钥留在本机 .env 或托管平台 Secret 中，不能提交仓库或写入本文。')
sec('自动评测','设置 TRACESCHOLAR_SAMPLE_DIR 指向组委会 pdf 目录。pytest tests -q 验证回归；scripts/evaluate_extended.py --output ../docs/evaluation/local.json 运行图表、细粒度检索、图谱与长文档检查。只有显式 --live 才调用已配置模型；模型请求会产生实际用量。')
sec('用户验收顺序','按 docs/PHASE6_TEST_GUIDE.md：图表/细粒度问答 → 版本与管理 → 阅读/翻译 → 工具 Agent → 批量/追踪 → 图谱/综述 → CSV 与失败恢复。每项记录本地或线上、文件、页码、截图和结果。')
sec('线上仍需验收','手动提交并推送后，确认 Render 采用对应 commit。检查 HTTPS、未认证 401、health、另一设备访问、冷启动、模型可用、合法演示数据与重部署磁盘行为。本轮没有自动改线上服务或提交赛事材料。')
sec('正式提交前','补参赛姓名、学校和团队；核对个人中心本届截止时间。审阅不超过 30 页技术说明，观看 5-8 分钟普通话 1080p MP4。提供评审可访问仓库/演示地址；评审凭证通过私密渠道。冻结最终 commit，保存上传回执。')
sec('明确待办','用户延后的视觉模型选型与接入：图片深度理解、扫描表格结构重建、可靠公式 LaTeX。另无通用新颖性证明、稠密检索、多用户隔离或分布式队列。这些边界应在正式材料和演示中如实保留。')
para('证据文件：docs/evaluation/phase6-local.json、phase6-live.json、phase6-author-followup.json、phase6-retrieval.json、phase6-multidoc.json；完整变更和边界：docs/PHASE6_PROGRESS.md。','small')
def footer(c,doc):
 c.setStrokeColor(C('#e1e5ec'));c.line(44,42,551,42);c.setFont('CJK',8);c.setFillColor(C('#798298'));c.drawString(44,28,'TraceScholar / 技术说明审阅稿 / 2026-11-16');c.drawRightString(551,28,str(doc.page))
OUT.parent.mkdir(parents=True,exist_ok=True)
SimpleDocTemplate(str(OUT),pagesize=(595.28,841.89),leftMargin=45,rightMargin=45,topMargin=45,bottomMargin=59,title='TraceScholar 技术说明审阅稿',author='TraceScholar').build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT)
