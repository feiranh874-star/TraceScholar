"""Create an explicitly labelled narrated screenshot draft (macOS say + FFmpeg).
This is not a continuous interactive screen recording or a final submission.
"""
from pathlib import Path
import json,os,re,subprocess,textwrap
from PIL import Image,ImageDraw,ImageFont,ImageOps
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/video';TMP=ROOT/'tmp/video';OUT.mkdir(parents=True,exist_ok=True);TMP.mkdir(parents=True,exist_ok=True)
FFMPEG=os.environ['TRACESCHOLAR_FFMPEG']
font_path=os.getenv('TRACESCHOLAR_CJK_FONT','/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
fonts=[ImageFont.truetype(font_path,n) for n in (24,44,25,21)]
scenes=json.loads((ROOT/'docs/delivery/video_scenes.json').read_text())
segments=[];summary=[];subtitles=[];clock=0
for i,s in enumerate(scenes):
 frame=Image.new('RGB',(1920,1080),'#f3f5fa');draw=ImageDraw.Draw(frame)
 draw.text((72,28),'TRACESCHOLAR  /  真实截图讲解草稿',font=fonts[0],fill='#6b65a7')
 draw.text((72,68),f'{i+1:02d}  '+s['title'],font=fonts[1],fill='#252942')
 im=Image.open(ROOT/'docs/delivery/screenshots'/s['image']).convert('RGB');im=ImageOps.contain(im,(1776,800),Image.Resampling.LANCZOS)
 x=(1920-im.width)//2;y=158+(800-im.height)//2;frame.paste(im,(x,y));draw.rectangle((x-1,y-1,x+im.width,y+im.height),outline='#d8dce8',width=2)
 draw.text((72,987),s['caption'],font=fonts[2],fill='#434b64')
 draw.text((72,1033),'审阅稿 · 2026-11-16 · 待补身份与线上验收；不等于正式提交',font=fonts[3],fill='#798298')
 framepath=TMP/f'{i:02d}.png';frame.save(framepath)
 speech=TMP/f'{i:02d}.txt';speech.write_text(s['narration']);audio=TMP/f'{i:02d}.aiff'
 subprocess.run(['say','-v','Tingting','-r','205','-o',str(audio),'-f',str(speech)],check=True)
 info=subprocess.run([FFMPEG,'-i',str(audio)],capture_output=True,text=True).stderr
 h,m,sec=re.search(r'Duration: (\d+):(\d+):([\d.]+)',info).groups();seconds=int(h)*3600+int(m)*60+float(sec);duration=max(40,seconds+2)
 target=TMP/f'{i:02d}.mp4'
 subprocess.run([FFMPEG,'-y','-loop','1','-i',str(framepath),'-i',str(audio),'-t',str(duration),'-vf','fps=25,format=yuv420p','-c:v','libx264','-preset','ultrafast','-tune','stillimage','-crf','24','-c:a','aac','-b:a','128k','-af','apad','-movflags','+faststart',str(target)],check=True,capture_output=True)
 segments.append(target);summary.append({'scene':i+1,'title':s['title'],'duration':round(duration,2),'audio_seconds':seconds})
 def stamp(t):
  ms=round(t*1000);return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
 # Human-readable narration subtitles, split into sentences at proportional timings.
 chunks=[v+'。' for v in s['narration'].split('。') if v];total=sum(len(v) for v in chunks);offset=clock
 for chunk in chunks:
  end=offset+seconds*len(chunk)/total;subtitles.append(f'{len(subtitles)+1}\n{stamp(offset)} --> {stamp(end)}\n{chunk}\n');offset=end
 clock+=duration
 print(json.dumps(summary[-1],ensure_ascii=False),flush=True)
manifest=TMP/'concat.txt';manifest.write_text('\n'.join("file '"+str(p)+"'" for p in segments))
video=OUT/'TraceScholar-演示讲解草稿.mp4'
subprocess.run([FFMPEG,'-y','-f','concat','-safe','0','-i',str(manifest),'-c','copy','-movflags','+faststart',str(video)],check=True,capture_output=True)
(OUT/'TraceScholar-演示讲解草稿.srt').write_text('\n'.join(subtitles))
(OUT/'manifest.json').write_text(json.dumps({'format':'MP4 H.264 AAC','width':1920,'height':1080,'fps':25,'seconds':round(clock,2),'voice':'macOS Tingting, Mandarin TTS','draft':True,'continuous_recording':False,'scenes':summary},ensure_ascii=False,indent=2))
print('TOTAL_SECONDS',round(clock,2));print(video)
