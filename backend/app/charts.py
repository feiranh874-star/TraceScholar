"""Validated CSV plots and reproducible scripts; never execute uploaded/model code."""
import base64
import csv
import io
import json
import math
import os
import threading
import tempfile
from typing import Literal
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router=APIRouter(prefix='/api/library',tags=['charts'])
_PLOT_LOCK=threading.Lock()
PLOT_CODE='''
import math
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
figure=Figure(figsize=(9,5.4),layout="constrained")
FigureCanvasAgg(figure)
labels=[r[0] for r in rows]
values=[r[1] for r in rows]
positions=list(range(len(rows)))
if kind in ("radar", "radar3d"):
    angles=[2*math.pi*i/len(rows) for i in positions]
    if kind=="radar":
        ax=figure.add_subplot(111,projection="polar")
        ax.plot(angles+[angles[0]],values+[values[0]],color="#5965d8")
        ax.fill(angles+[angles[0]],values+[values[0]],alpha=.15)
        ax.set_xticks(angles,labels)
    else:
        ax=figure.add_subplot(111,projection="3d")
        xs=[r*math.cos(t) for r,t in zip(values,angles)]
        ys=[r*math.sin(t) for r,t in zip(values,angles)]
        zs=[r[2] for r in rows]
        ax.plot(xs+[xs[0]],ys+[ys[0]],zs+[zs[0]],marker="o",color="#5965d8")
        for a,b,c,label in zip(xs,ys,zs,labels): ax.text(a,b,c,label)
        ax.set_zlabel(z,parse_math=False)
        ax.set_xlabel(y+" × cos(angle)",parse_math=False)
        ax.set_ylabel(y+" × sin(angle)",parse_math=False)
elif kind=="scatter3d":
    ax=figure.add_subplot(111,projection="3d")
    ax.scatter([float(r[0]) for r in rows],values,[r[2] for r in rows],color="#5965d8")
    ax.set_xlabel(x,parse_math=False);ax.set_ylabel(y,parse_math=False);ax.set_zlabel(z,parse_math=False)
else:
    ax=figure.subplots()
    if kind=="line": ax.plot(positions,values,color="#5965d8",linewidth=2)
    elif kind=="bar": ax.bar(positions,values,color="#5965d8")
    elif kind=="scatter": ax.scatter([float(r[0]) for r in rows],values,color="#5965d8")
    elif kind=="table":
        ax.axis("off")
        ax.table(cellText=[[r[0],str(r[1])] for r in rows],colLabels=[x,y],loc="center",cellLoc="left")
    if kind not in ("scatter","table"):
        ticks=positions[::max(1,len(rows)//12)]
        ax.set_xticks(ticks,[labels[i] for i in ticks],rotation=25,ha="right",parse_math=False)
    if kind!="table":
        ax.set_xlabel(x,parse_math=False);ax.set_ylabel(y,parse_math=False);ax.grid(axis="y",alpha=.2)
'''

def finite(value):
    result=float(value)
    if not math.isfinite(result) or abs(result)>1e100:raise ValueError('数值必须有限，不能含 NaN/Infinity。')
    return result

@router.post('/chart')
def chart(file:UploadFile=File(...),x:str=Form(...),y:str=Form(...),
          kind:Literal['line','bar','scatter','radar','radar3d','scatter3d','table']=Form(default='line'),z:str=Form(default='')):
    try:data=file.file.read(1024*1024+1)
    finally:file.file.close()
    if len(data)>1024*1024:raise HTTPException(413,'CSV 限制为 1 MiB。')
    try:
        reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig')),strict=True);fields=reader.fieldnames or []
        if len(fields)>50 or len(set(fields))!=len(fields) or any(not f or len(f)>100 for f in fields):raise ValueError('列名重复或列数超过 50。')
        if x not in fields or y not in fields or (kind in ('radar3d','scatter3d') and z not in fields):raise ValueError('请选择存在的 X/Y 列，三维图还需 Z 列。')
        rows=[]
        for row in reader:
            if len(rows)>=1000:raise ValueError('最多支持 1000 行。')
            if None in row or any(v is None for v in row.values()):raise ValueError('CSV 行列数量不一致。')
            if len(row[x])>120:raise ValueError('X 标签过长。')
            value=finite(row[y])
            if kind in ('radar','radar3d') and value<0:raise ValueError('雷达图半径不能为负。')
            if kind in ('scatter','scatter3d'):finite(row[x])
            rows.append([row[x],value]+([finite(row[z])] if kind in ('radar3d','scatter3d') else []))
        if not rows:raise ValueError('CSV 没有数据行。')
        if kind in ('radar','radar3d') and not 3<=len(rows)<=24:raise ValueError('雷达图需 3–24 个类别。')
        if kind=='table' and len(rows)>40:raise ValueError('图片表格最多 40 行；其他图最多 1000 行。')
    except (ValueError,UnicodeError,csv.Error) as error:raise HTTPException(422,'CSV 无法绘图：'+str(error)) from error
    os.environ.setdefault('MPLCONFIGDIR',str(Path(tempfile.gettempdir())/'tracescholar-matplotlib'))
    # Fixed audited template. Variables carry validated data and never become executable source.
    scope={'rows':rows,'x':x,'y':y,'z':z,'kind':kind}
    with _PLOT_LOCK:
        exec(compile(PLOT_CODE,'fixed_chart_template','exec'),scope)
        buffer=io.BytesIO();scope['figure'].savefig(buffer,format='png',dpi=160)
    values=[r[1] for r in rows];low=min(values);high=max(values);mean=sum(v/len(values) for v in values)
    caption=f'{y} 的 {len(rows)} 个观测值。最小值 {low:g}，最大值 {high:g}，均值 {mean:g}。'
    if kind in ('radar','radar3d'):caption+='类别角度按 CSV 行序均匀排列；半径为 Y 原始值，未自动归一化。'
    if kind in ('radar3d','scatter3d'):caption+=f'高度轴使用 {z} 原始数值。'
    caption+='未进行显著性检验；图中变化不代表因果关系。'
    script=('import json\nrows=json.loads('+repr(json.dumps(rows,ensure_ascii=True))+')\n'+
            'x='+repr(x)+'\ny='+repr(y)+'\nz='+repr(z)+'\nkind='+repr(kind)+'\n'+PLOT_CODE+'\nfigure.savefig("figure.png",dpi=160)\n')
    return {'image':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),'caption':caption,'script':script,
            'rows':len(rows),'table':{'headers':[x,y]+([z] if kind in ('radar3d','scatter3d') else []),'rows':rows},
            'stats':{'min':low,'max':high,'mean':mean},'method':'固定 Matplotlib 模板；程序计算统计值，不执行上传或模型代码'}
