"""HTML for the search / multi-select / task dashboard page."""


SEARCH_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#070a11">
<title>影片自动化 · 私人影院</title>
<style>
:root{
  color-scheme:dark;
  --bg:#070a11;
  --bg-2:#0a0f19;
  --surface:rgba(18,23,36,.86);
  --surface-2:rgba(11,15,24,.72);
  --ink:#f4efe4;
  --muted:#a9a396;
  --line:rgba(216,180,108,.20);
  --line-soft:rgba(255,255,255,.075);
  --gold:#d4af6a;
  --gold-2:#f4d99a;
  --gold-deep:#b08a45;
  --green:#5fd3a0;
  --amber:#e5b567;
  --red:#e47c7c;
  --radius:20px;
  --serif:"Songti SC","STSong","Noto Serif CJK SC","Iowan Old Style",Palatino,Georgia,serif;
  --sans:"SF Pro Display","PingFang SC","HarmonyOS Sans SC","MiSans","Source Han Sans SC","Noto Sans CJK SC","Microsoft YaHei UI","Microsoft YaHei","Hiragino Sans GB",-apple-system,BlinkMacSystemFont,sans-serif;
  --shadow:0 40px 100px -48px rgba(0,0,0,.95),inset 0 1px 0 rgba(255,255,255,.055);
}
*{box-sizing:border-box}
html{background:#060910;scroll-behavior:smooth}
body{
  margin:0;color:var(--ink);min-height:100vh;
  font:17px/1.72 var(--sans);
  letter-spacing:.012em;
  text-rendering:optimizeLegibility;
  -webkit-font-smoothing:antialiased;
  -moz-osx-font-smoothing:grayscale;
  font-feature-settings:"kern" 1,"liga" 1;
  background:
    radial-gradient(1200px 680px at 12% -12%, rgba(96,78,150,.35), transparent 62%),
    radial-gradient(950px 600px at 100% -4%, rgba(183,140,68,.16), transparent 58%),
    linear-gradient(180deg,#060910 0%,#090d16 42%,#060910 100%);
  -webkit-font-smoothing:antialiased;
}
body::before{
  content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.12;
  background-image:repeating-linear-gradient(0deg,rgba(255,255,255,.055) 0 1px,transparent 1px 4px);
  mix-blend-mode:soft-light;
}
body::after{
  content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
  background:radial-gradient(ellipse at 50% 20%,transparent 35%,rgba(0,0,0,.55) 100%);
}
::selection{background:rgba(212,175,106,.32);color:#fff}
a{color:var(--gold-2);text-decoration:none}
button{font:inherit}
.topbar{
  position:sticky;top:0;z-index:20;
  background:rgba(6,9,16,.78);
  border-bottom:1px solid rgba(216,180,108,.16);
  backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
}
.topbar::before{
  content:"";position:absolute;left:0;right:0;top:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(244,217,154,.85),transparent);
}
.topbar-inner{max-width:1120px;margin:0 auto;padding:14px 24px;display:flex;align-items:center;gap:18px}
.brand{display:flex;align-items:center;gap:12px;color:var(--ink)}
.brand-mark{
  width:40px;height:40px;border-radius:11px;display:grid;place-items:center;
  color:#1a1206;font-weight:800;font-size:19px;font-family:var(--serif);
  background:linear-gradient(135deg,#f7e2ad,#c69b4f 55%,#8f682d);
  box-shadow:0 0 0 1px rgba(255,235,190,.35),0 10px 28px -8px rgba(212,175,106,.55);
}
.brand-text{display:flex;flex-direction:column;line-height:1.15}
.brand-text b{font-family:var(--serif);font-size:17px;letter-spacing:.12em;font-weight:600}
.brand-text small{font-size:8.5px;letter-spacing:.28em;color:rgba(244,217,154,.62);font-weight:700;margin-top:2px}
.nav{display:flex;gap:4px;margin-left:auto;font-size:13.5px}
.nav a{padding:9px 15px;border-radius:9px;color:rgba(244,239,228,.6);font-weight:600;letter-spacing:.04em;transition:.2s}
.nav a:hover{color:var(--gold-2);background:rgba(216,180,108,.07)}
.nav a.active{color:#1a1206;background:linear-gradient(135deg,#f0d596,#c69b4f);box-shadow:0 6px 18px -8px rgba(212,175,106,.7)}
main{position:relative;z-index:1;max-width:1120px;margin:0 auto;padding:40px 24px 70px}
.hero{display:flex;align-items:flex-end;justify-content:space-between;gap:34px;padding:10px 4px 32px}
.hero-copy{max-width:720px}
.eyebrow{display:inline-flex;align-items:center;gap:12px;font-size:9.5px;font-weight:800;letter-spacing:.32em;color:var(--gold);margin-bottom:18px}
.eyebrow::before{content:"";width:42px;height:1px;background:linear-gradient(90deg,transparent,var(--gold))}
.hero h1{
  font-family:var(--serif);font-weight:600;font-size:clamp(38px,5.6vw,66px);
  line-height:1.06;letter-spacing:.01em;margin:0 0 18px;
  background:linear-gradient(180deg,#fffdf6 0%,#eee2cb 52%,#b99a5e 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.hero h1 em{
  font-style:normal;
  background:linear-gradient(100deg,#f8e4b0,#d4af6a 48%,#a77d3f);
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.hero p{margin:0;max-width:640px;color:var(--muted);font-size:14.5px;line-height:1.8}
.flow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;white-space:nowrap;padding-bottom:4px}
.flow span{
  padding:8px 12px;border-radius:7px;font-size:10.5px;letter-spacing:.14em;font-weight:700;color:rgba(244,239,228,.72);
  background:rgba(255,255,255,.025);border:1px solid rgba(216,180,108,.18);
}
.flow i{font-style:normal;color:rgba(212,175,106,.4);font-size:12px}
.panel{
  position:relative;overflow:hidden;
  background:linear-gradient(160deg,rgba(23,29,45,.92),rgba(9,13,22,.94));
  border:1px solid var(--line);border-radius:var(--radius);
  padding:28px;margin-bottom:22px;box-shadow:var(--shadow);
  animation:rise .5s cubic-bezier(.2,.7,.2,1) both;
}
.panel::before{
  content:"";position:absolute;left:0;right:0;top:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(244,217,154,.55),transparent);
}
.panel:nth-of-type(2){animation-delay:.06s}
.panel:nth-of-type(3){animation-delay:.12s}
@keyframes rise{from{transform:translateY(14px)}to{transform:none}}
.panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
h2{font-family:var(--serif);font-size:22px;font-weight:600;letter-spacing:.04em;margin:0 0 5px;color:#fbf7ee}
.hint{color:var(--muted);font-size:12.5px;line-height:1.7;margin:0}
.search{display:flex;gap:10px;margin-top:20px}
.search-field{
  flex:1;display:flex;align-items:center;gap:12px;min-width:0;padding:0 16px;
  background:rgba(0,0,0,.32);border:1px solid rgba(216,180,108,.26);border-radius:12px;
  transition:.22s;box-shadow:inset 0 1px 6px rgba(0,0,0,.45);
}
.search-field:focus-within{border-color:rgba(244,217,154,.72);box-shadow:0 0 0 3px rgba(212,175,106,.10),inset 0 1px 6px rgba(0,0,0,.45)}
.search-field svg{flex:none;color:rgba(212,175,106,.72)}
.search-field input{
  border:0;outline:0;background:transparent;width:100%;min-width:0;padding:15px 0;
  font:inherit;font-size:16px;color:var(--ink);letter-spacing:.01em;
}
.search-field input::placeholder{color:rgba(169,163,150,.55)}
.search-field input::-webkit-search-cancel-button{-webkit-appearance:none;appearance:none;}
button{
  border:0;border-radius:11px;padding:12px 20px;font-size:13px;font-weight:800;letter-spacing:.06em;
  cursor:pointer;background:linear-gradient(135deg,#f4dca2,#c99d50 60%,#9e7434);color:#1b1307;
  box-shadow:0 10px 26px -12px rgba(212,175,106,.65),inset 0 1px 0 rgba(255,255,255,.4);
  transition:transform .16s,box-shadow .16s,opacity .16s,filter .16s;
}
button:hover{transform:translateY(-1px);filter:brightness(1.05);box-shadow:0 16px 32px -14px rgba(212,175,106,.7)}
button:active{transform:translateY(0)}
button:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none;filter:none}
button.secondary{background:rgba(255,255,255,.04);color:rgba(244,239,228,.78);box-shadow:none;border:1px solid rgba(216,180,108,.18);padding:9px 14px;font-size:12px;letter-spacing:.04em}
button.secondary:hover{background:rgba(216,180,108,.09);color:var(--gold-2)}
.search button{display:flex;align-items:center;gap:8px;padding:0 24px;min-height:53px;white-space:nowrap}
.suggest-wrap{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-top:13px}
.suggest-label{font-size:9.5px;font-weight:800;letter-spacing:.16em;color:rgba(212,175,106,.65);white-space:nowrap}
.suggestions{display:flex;flex-wrap:wrap;gap:7px}
button.suggestion{background:rgba(212,175,106,.06);color:rgba(244,217,154,.9);border:1px solid rgba(212,175,106,.25);border-radius:5px;padding:5px 10px;font-size:11px;font-weight:600;letter-spacing:.02em;box-shadow:none;transition:.16s}
button.suggestion:hover{background:rgba(212,175,106,.14);border-color:rgba(244,217,154,.6);transform:none;box-shadow:none}
.suggest-loading{font-size:11px;color:rgba(169,163,150,.55)}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:14px}
.chip{font-size:10.5px;font-weight:700;letter-spacing:.08em;color:rgba(244,239,228,.55);background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.07);border-radius:6px;padding:4px 9px}
.chip-btn{cursor:pointer;border:1px solid rgba(212,175,106,.35);background:rgba(212,175,106,.12);color:#f4dca2;font:inherit}
.chip-btn:hover{background:rgba(212,175,106,.2);transform:none}
.stats-strip{margin-top:12px;font-size:13px;color:rgba(214,206,192,.85);letter-spacing:.02em}
.health-strip{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.health-pill{font-size:11.5px;padding:3px 9px;border-radius:999px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:rgba(214,206,192,.8)}
.health-pill.ok{color:#8fd7b0;border-color:rgba(95,211,160,.3)}
.health-pill.bad{color:#e9a1a1;border-color:rgba(228,124,124,.35)}
.status{margin-top:14px;font-size:12.5px;color:var(--muted);min-height:20px}
.status.error{color:var(--red)}
.status:empty{display:none}
.warning{
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:22px;
  background:linear-gradient(90deg,rgba(80,54,13,.55),rgba(28,23,14,.55));
  border:1px solid rgba(229,181,103,.35);color:#f0cf95;border-radius:12px;padding:13px 16px;font-size:12.5px;line-height:1.6;
}
.warning a{font-weight:700;color:var(--gold-2);white-space:nowrap}
.hidden{display:none!important}
.results{display:flex;flex-direction:column;gap:10px;margin-top:20px}
.result{
  display:flex;gap:15px;align-items:flex-start;padding:17px 18px;cursor:pointer;
  background:linear-gradient(180deg,rgba(17,22,35,.72),rgba(9,13,21,.72));
  border:1px solid rgba(255,255,255,.075);border-radius:13px;
  transition:border-color .2s,box-shadow .2s,transform .2s,background .2s;
}
.result:hover{border-color:rgba(216,180,108,.42);transform:translateY(-1px);box-shadow:0 18px 40px -32px #000}
.result.selected{
  border-color:rgba(244,217,154,.6);
  background:linear-gradient(180deg,rgba(48,40,24,.55),rgba(14,17,25,.82));
  box-shadow:0 0 0 3px rgba(212,175,106,.08),0 18px 40px -30px #000;
}
.result input[type=checkbox]{
  appearance:none;-webkit-appearance:none;width:19px;height:19px;flex:none;margin:3px 0 0;
  border:1px solid rgba(216,180,108,.45);border-radius:4px;background:rgba(0,0,0,.3);
  cursor:pointer;position:relative;transition:.16s;
}
.result input[type=checkbox]:checked{background:linear-gradient(135deg,#f4dca2,#c99d50);border-color:#f4dca2}
.result input[type=checkbox]:checked::after{
  content:"";position:absolute;left:6px;top:2px;width:4px;height:9px;
  border:solid #1b1307;border-width:0 2px 2px 0;transform:rotate(45deg);
}
.result-body{min-width:0;flex:1}
.result-title{font-size:15.5px;font-weight:600;line-height:1.5;letter-spacing:.01em;word-break:break-word;color:#f7f2e8}
.result-zh{font-size:13.5px;line-height:1.55;margin-top:4px;word-break:break-word;color:rgba(224,190,120,.88)}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;font-size:12px;color:var(--muted)}
.badge{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);border-radius:5px;padding:3px 8px;white-space:nowrap;font-weight:600;letter-spacing:.03em}
.badge.good{background:rgba(95,211,160,.08);border-color:rgba(95,211,160,.28);color:#7fe4b8}
.badge.warn{background:rgba(229,181,103,.08);border-color:rgba(229,181,103,.28);color:#f0cf95}
.badge.hash{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:rgba(169,163,150,.72);letter-spacing:0}
.actions{
  display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:20px;padding:13px 15px;
  border:1px solid rgba(216,180,108,.18);border-radius:12px;background:rgba(0,0,0,.22);
}
.actions .count{margin-right:auto;color:rgba(244,239,228,.65);font-size:12px;letter-spacing:.04em}
.actions .count b{color:var(--gold-2);font-size:15px;font-family:var(--serif)}
.linkbtn{background:none;color:rgba(244,217,154,.78);padding:6px 4px;font-size:11.5px;font-weight:700;letter-spacing:.04em;box-shadow:none}
.linkbtn:hover{background:none;transform:none;color:#fff}
.jobs{display:flex;flex-direction:column;gap:11px;margin-top:18px}
.job{
  border:1px solid rgba(255,255,255,.075);border-left:2px solid rgba(169,163,150,.35);
  border-radius:12px;padding:17px 18px;background:linear-gradient(180deg,rgba(17,22,35,.7),rgba(9,13,21,.72));
  transition:box-shadow .2s,transform .2s,border-color .2s;
}
.job:hover{box-shadow:0 20px 44px -32px #000;transform:translateY(-1px)}
.job-uploading,.job-queued{border-left-color:rgba(169,163,150,.5)}
.job-downloading{border-left-color:#6ea8fe}
.job-awaiting_source{border-left-color:#e5b567}
.job-processing{border-left-color:#b79cff}
.job-completed{border-left-color:#5fd3a0}
.job-failed{border-left-color:#e47c7c}
.job-head{display:flex;gap:12px;align-items:flex-start}
.job-title{font-family:var(--serif);font-size:17px;font-weight:600;letter-spacing:.02em;flex:1;min-width:0;word-break:break-word;line-height:1.45;color:#fbf7ee}
.pill{font-size:9.5px;font-weight:800;letter-spacing:.1em;border-radius:4px;padding:4px 8px;background:rgba(255,255,255,.04);color:rgba(244,239,228,.7);white-space:nowrap;border:1px solid rgba(255,255,255,.07)}
.pill.downloading{background:rgba(110,168,254,.09);color:#9cc4ff;border-color:rgba(110,168,254,.22)}
.pill.awaiting_source{background:rgba(229,181,103,.09);color:#f0cf95;border-color:rgba(229,181,103,.25)}
.pill.processing{background:rgba(183,156,255,.09);color:#cbb8ff;border-color:rgba(183,156,255,.22)}
.pill.completed{background:rgba(95,211,160,.09);color:#7fe4b8;border-color:rgba(95,211,160,.24)}
.pill.failed{background:rgba(228,124,124,.09);color:#f1a3a3;border-color:rgba(228,124,124,.24)}
.job-meta{display:flex;flex-wrap:wrap;gap:10px;color:rgba(178,172,160,.88);font-size:12.5px;margin-top:9px;letter-spacing:.02em}
.job-meta span{white-space:nowrap}
.progress{height:5px;border-radius:999px;background:rgba(255,255,255,.055);overflow:hidden;margin-top:13px}
.progress > i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#9e7434,#f4dca2,#d4af6a);width:0;transition:width .4s ease}
.progress.indeterminate > i{width:30%;animation:slide 1.5s ease-in-out infinite}
@keyframes slide{0%{margin-left:-30%}100%{margin-left:100%}}
.job-error{color:#f1a3a3;font-size:11.5px;margin-top:10px;word-break:break-word;background:rgba(228,124,124,.07);border:1px solid rgba(228,124,124,.18);border-radius:7px;padding:8px 10px}
.job-hint{color:#f0cf95;font-size:12.5px;margin-top:10px;border-left:2px solid rgba(229,181,103,.5);padding:2px 0 2px 9px;line-height:1.5}
.job-archive{color:#8fd7b0;font-size:12.5px;margin-top:10px;word-break:break-all;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.job-usage{color:#e8c07d;font-size:12.5px;margin-top:8px;word-break:break-all;font-variant-numeric:tabular-nums}
.job-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;font-size:13px}
.job-links a{display:inline-flex;align-items:center;gap:6px;padding:7px 11px;border-radius:6px;font-weight:700;letter-spacing:.04em;background:rgba(212,175,106,.09);color:var(--gold-2);border:1px solid rgba(212,175,106,.22)}
.job-links a:hover{background:rgba(212,175,106,.16)}
.job-actions{margin-top:12px;display:flex;gap:8px}
button.danger{background:rgba(228,124,124,.06);color:#e9a1a1;padding:7px 12px;font-size:10.5px;letter-spacing:.06em;box-shadow:none;border:1px solid rgba(228,124,124,.2)}
button.danger:hover{background:rgba(228,124,124,.14);transform:none;box-shadow:none}
button.danger.armed{background:#b23a3a;color:#fff;border-color:#b23a3a}
button.retry{background:rgba(216,180,108,.08);color:#f0cf95;padding:7px 12px;font-size:10.5px;letter-spacing:.06em;box-shadow:none;border:1px solid rgba(216,180,108,.25)}
button.retry:hover{background:rgba(216,180,108,.16);transform:none;box-shadow:none}
button.share{background:rgba(95,211,160,.08);color:#8fd7b0;padding:7px 12px;font-size:10.5px;letter-spacing:.06em;box-shadow:none;border:1px solid rgba(95,211,160,.25)}
button.share:hover{background:rgba(95,211,160,.16);transform:none;box-shadow:none}
.share-panel{display:flex;flex-direction:column;align-items:center;gap:10px;margin-top:14px;padding:16px;border-radius:12px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07)}
.modal{position:fixed;inset:0;z-index:90;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.66);backdrop-filter:blur(3px)}
.modal.hidden{display:none}
.modal-card{position:relative;width:min(92vw,390px);padding:26px 24px 22px;border-radius:18px;text-align:center;background:linear-gradient(180deg,rgba(24,28,38,.99),rgba(12,15,22,.99));border:1px solid rgba(216,180,108,.28);box-shadow:0 30px 80px -40px #000}
.modal-title{margin-bottom:16px;font-size:15px;font-weight:700;letter-spacing:.04em;color:#f4e7c9}
.modal-close{position:absolute;top:8px;right:10px;width:32px;height:32px;padding:0;border:0;background:transparent;color:rgba(233,226,214,.6);font-size:24px;line-height:1;cursor:pointer}
.modal-close:hover{color:#f4e7c9;background:transparent;transform:none;box-shadow:none}
.share-qr{display:block;margin:0 auto;width:240px;height:240px;padding:12px;border-radius:12px;background:#fff}
.share-url{margin-top:16px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:15px;line-height:1.5;color:#8fd7b0;word-break:break-all}
.share-hint{margin-top:10px;font-size:13px;line-height:1.7;color:rgba(214,206,192,.82)}
.share-warning{margin-top:10px;font-size:13px;line-height:1.7;color:#f0cf95;text-align:center}
button.share-copy{margin-top:16px;padding:9px 20px;font-size:13px;border-radius:9px;background:rgba(255,255,255,.08);color:#f4e7c9;border:1px solid rgba(255,255,255,.16)}
button.share-copy:hover{background:rgba(255,255,255,.16);transform:none;box-shadow:none}
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;color:rgba(169,163,150,.5);font-size:11.5px;letter-spacing:.08em;padding:40px 10px;text-align:center}
.empty::before{content:"◇";font-size:20px;color:rgba(212,175,106,.35);line-height:1}
.upload-row{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr) auto;gap:10px;margin-top:18px}
.upload-row input[type=file]{width:100%;min-width:0;border:1px dashed rgba(216,180,108,.28);border-radius:10px;padding:10px 12px;background:rgba(0,0,0,.22);font-size:12px;color:rgba(244,239,228,.62);cursor:pointer}
.upload-row input[type=file]:hover{border-color:rgba(244,217,154,.6);background:rgba(212,175,106,.05)}
.upload-row input[type=file]::file-selector-button{border:0;border-radius:6px;background:rgba(212,175,106,.13);color:var(--gold-2);font-weight:700;padding:7px 10px;margin-right:10px;cursor:pointer;font:inherit;font-size:11px;letter-spacing:.04em}
.upload-row input[type=text]{width:100%;min-width:0;border:1px solid rgba(216,180,108,.22);border-radius:10px;padding:12px 13px;background:rgba(0,0,0,.25);font:inherit;font-size:13px;color:var(--ink);outline:0}
.upload-row input[type=text]:focus{border-color:rgba(244,217,154,.6);box-shadow:0 0 0 3px rgba(212,175,106,.08)}
.upload-row button{white-space:nowrap}
progress{appearance:none;-webkit-appearance:none;width:100%;height:5px;border:0;border-radius:999px;overflow:hidden;margin-top:14px;background:rgba(255,255,255,.06)}
progress::-webkit-progress-bar{background:rgba(255,255,255,.06);border-radius:999px}
progress::-webkit-progress-value{background:linear-gradient(90deg,#9e7434,#f4dca2);border-radius:999px}
progress::-moz-progress-bar{background:linear-gradient(90deg,#9e7434,#f4dca2);border-radius:999px}
progress[hidden]{display:none}
.footer{position:relative;z-index:1;max-width:1120px;margin:0 auto;padding:0 24px 30px;color:rgba(169,163,150,.45);font-size:10.5px;letter-spacing:.08em;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.footer a{color:rgba(212,175,106,.65);font-weight:600}
@media(max-width:860px){.hero{flex-direction:column;align-items:flex-start;gap:22px}.flow{white-space:normal}}
@media(max-width:650px){
  main{padding:26px 12px 48px}
  .topbar-inner{padding:11px 14px}
  .brand-text small{display:none}
  .brand-text b{font-size:15px}
  .panel{padding:18px;border-radius:16px}
  .hero h1{font-size:38px}
  .hero p{font-size:13.5px}
  .search{flex-direction:column}
  .search button{min-height:46px;justify-content:center;width:100%}
  .upload-row{grid-template-columns:1fr}
  .upload-row button{width:100%}
  .job-meta{gap:7px}
  .actions .count{width:100%;margin-right:0}
  .footer{padding:0 14px 24px}
}

/* ---------- v2 视觉升级 ---------- */
.result{padding-left:21px}
.result::before{
  content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
  background:#3a4152;opacity:.85;transition:opacity .2s;
}
.result[data-health="good"]::before{background:linear-gradient(180deg,#5fd3a0,#2f9c72)}
.result[data-health="warn"]::before{background:linear-gradient(180deg,#e5b567,#b8873a)}
.result[data-health="bad"]::before{background:linear-gradient(180deg,#e47c7c,#a94a4a)}
.result:hover::before{opacity:1}
.badge.tag{background:rgba(212,175,106,.10);border-color:rgba(212,175,106,.30);color:#f2d69a;letter-spacing:.04em}
.job-meta{font-variant-numeric:tabular-nums}
.job-meta .dot{color:rgba(169,163,150,.4)}
.job-title{letter-spacing:.01em}
.job{padding:16px 18px 15px}
.pill::before{content:"";display:inline-block;width:5px;height:5px;border-radius:50%;background:currentColor;margin-right:6px;vertical-align:middle;opacity:.85}
button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid rgba(244,217,154,.65);outline-offset:2px}
.panel{box-shadow:0 50px 120px -60px rgba(0,0,0,.95),inset 0 1px 0 rgba(255,255,255,.06)}
@media(max-width:650px){
  .result{padding-left:16px}
  .job-actions{width:100%}
  .job-actions button{flex:1}
  .job-links a{flex:1;justify-content:center}
}

/* ================= 主题层：ink（默认，现代中性） ================= */
:root{
  --bg:#0a0c11;--bg-2:#0e1118;
  --surface:#12151c;--surface-2:#0d1016;
  --ink:#e9ecf2;--muted:#98a1b2;
  --line:rgba(255,255,255,.09);--line-soft:rgba(255,255,255,.06);
  --accent:#8ab4ff;--accent-2:#cfe0ff;--accent-deep:#5f86d8;
  --gold:#8ab4ff;--gold-2:#cfe0ff;--gold-deep:#5f86d8;
  --radius:16px;
  --serif:"SF Pro Display","PingFang SC","HarmonyOS Sans SC","Microsoft YaHei UI",-apple-system,sans-serif;
}
body{
  background:
    radial-gradient(900px 520px at 8% -10%, rgba(96,124,204,.16), transparent 60%),
    radial-gradient(800px 480px at 100% 0%, rgba(120,96,180,.10), transparent 58%),
    linear-gradient(180deg,#0a0c11 0%,#0d1017 48%,#0a0c11 100%);
}
body::before{opacity:.05}
body::after{background:radial-gradient(ellipse at 50% 0%,transparent 45%,rgba(0,0,0,.42) 100%)}
.topbar{background:rgba(10,12,17,.82);border-bottom:1px solid rgba(255,255,255,.07)}
.topbar::before{background:linear-gradient(90deg,transparent,rgba(138,180,255,.5),transparent)}
.brand-mark{
  background:linear-gradient(135deg,#b9d0ff,#7ba0f0 55%,#4a67b8);
  color:#0a1020;
  box-shadow:0 0 0 1px rgba(190,214,255,.28),0 10px 26px -10px rgba(110,150,255,.45);
}
.brand-text small{color:rgba(160,185,240,.7)}
.nav a{color:rgba(233,236,242,.62)}
.nav a:hover{color:var(--accent-2);background:rgba(138,180,255,.08)}
.nav a.active{color:#0a1020;background:linear-gradient(135deg,#c6d9ff,#86a8f5)}
.eyebrow{color:var(--accent)}
.eyebrow::before{background:linear-gradient(90deg,transparent,var(--accent))}
.hero h1{
  font-family:var(--sans);font-weight:640;letter-spacing:-.015em;
  background:linear-gradient(180deg,#ffffff 0%,#dbe4f5 60%,#93a4c2 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.hero h1 em{
  background:linear-gradient(100deg,#cfe0ff,#8ab4ff 55%,#6f8cff);
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.flow span{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);color:rgba(233,236,242,.7)}
.flow i{color:rgba(138,180,255,.4)}
.panel{
  background:linear-gradient(180deg,rgba(18,21,28,.92),rgba(12,15,21,.94));
  border:1px solid rgba(255,255,255,.08);
  box-shadow:0 40px 90px -60px #000,inset 0 1px 0 rgba(255,255,255,.05);
}
.panel::before{background:linear-gradient(90deg,transparent,rgba(138,180,255,.4),transparent)}
.result{
  background:linear-gradient(180deg,rgba(19,23,31,.78),rgba(13,16,22,.8));
  border:1px solid rgba(255,255,255,.07);border-radius:14px;
}
.result:hover{border-color:rgba(138,180,255,.4);box-shadow:0 18px 40px -30px #000}
.result.selected{
  border-color:rgba(170,200,255,.55);
  background:linear-gradient(180deg,rgba(26,34,50,.7),rgba(14,18,26,.86));
  box-shadow:0 0 0 3px rgba(138,180,255,.09),0 18px 40px -30px #000;
}
.result input[type=checkbox]{border-color:rgba(160,185,240,.4)}
.result input[type=checkbox]:checked{background:linear-gradient(135deg,#cfe0ff,#86a8f5);border-color:#cfe0ff}
.result input[type=checkbox]:checked::after{border-color:#0a1020}
.result-title{color:#eef1f7;font-weight:580}
.result-zh{color:rgba(160,185,240,.9)}
.badge{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:#c3cbd9}
.badge.good{background:rgba(95,211,160,.09);border-color:rgba(95,211,160,.25);color:#84e0b6}
.badge.warn{background:rgba(229,181,103,.09);border-color:rgba(229,181,103,.25);color:#eed3a0}
.badge.tag{background:rgba(138,180,255,.10);border-color:rgba(138,180,255,.26);color:#bcd4ff}
.badge.hash{color:rgba(150,160,180,.7)}
.chip,.chip-btn{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.08);color:rgba(233,236,242,.72)}
.chip-btn{border-color:rgba(138,180,255,.3);background:rgba(138,180,255,.1);color:#c7dbff}
.chip-btn:hover{background:rgba(138,180,255,.16)}
.result::before{background:#2b3240}
.result[data-health="good"]::before{background:linear-gradient(180deg,#5fd3a0,#2f9c72)}
.result[data-health="warn"]::before{background:linear-gradient(180deg,#e5b567,#b8873a)}
.result[data-health="bad"]::before{background:linear-gradient(180deg,#e47c7c,#a94a4a)}
.job{
  background:linear-gradient(180deg,rgba(19,23,31,.8),rgba(12,15,21,.82));
  border:1px solid rgba(255,255,255,.07);border-left-width:3px;border-radius:14px;
}
.job-title{font-family:var(--sans);font-weight:620;letter-spacing:-.005em;font-size:16px;color:#eef1f7}
.pill{background:rgba(255,255,255,.05);color:rgba(233,236,242,.75);border:1px solid rgba(255,255,255,.08);border-radius:999px;padding:4px 10px}
.pill.downloading{background:rgba(110,168,254,.12);color:#a6c8ff;border-color:rgba(110,168,254,.25)}
.pill.awaiting_source{background:rgba(229,181,103,.12);color:#f0cf95;border-color:rgba(229,181,103,.26)}
.pill.processing{background:rgba(183,156,255,.12);color:#cfbdff;border-color:rgba(183,156,255,.24)}
.pill.completed{background:rgba(95,211,160,.12);color:#84e0b6;border-color:rgba(95,211,160,.26)}
.pill.failed{background:rgba(228,124,124,.12);color:#f0a5a5;border-color:rgba(228,124,124,.26)}
.job-meta{color:rgba(180,190,205,.85)}
.progress{background:rgba(255,255,255,.07)}
.progress > i{background:linear-gradient(90deg,#5f86d8,#8ab4ff,#cfe0ff)}
.job-links a{background:rgba(138,180,255,.1);color:#bcd4ff;border:1px solid rgba(138,180,255,.24);border-radius:8px}
.job-links a:hover{background:rgba(138,180,255,.18)}
button.retry{background:rgba(138,180,255,.1);color:#bcd4ff;border:1px solid rgba(138,180,255,.26)}
button.retry:hover{background:rgba(138,180,255,.18)}
.stats-strip{color:rgba(190,200,215,.85)}
.health-pill{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:rgba(190,200,215,.85);border-radius:999px}
.health-pill.ok{color:#84e0b6;border-color:rgba(95,211,160,.26)}
.health-pill.bad{color:#f0a5a5;border-color:rgba(228,124,124,.28)}
.suggest-label{color:rgba(160,185,240,.8)}
.suggestion{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);color:#c9d3e4}
.suggestion:hover{background:rgba(138,180,255,.12);border-color:rgba(138,180,255,.3)}
.search-field{border:1px solid rgba(255,255,255,.1);background:rgba(10,13,19,.7);border-radius:14px}
.search-field:focus-within{border-color:rgba(138,180,255,.5);box-shadow:0 0 0 3px rgba(138,180,255,.1)}
button[type=submit],.search button{
  background:linear-gradient(135deg,#b9d0ff,#7ba0f0 60%,#5f86d8);
  color:#0a1020;border-radius:12px;font-weight:700;
  box-shadow:0 12px 30px -14px rgba(110,150,255,.55);
}
button[type=submit]:hover,.search button:hover{box-shadow:0 16px 36px -14px rgba(110,150,255,.7)}
.actions{border:1px solid rgba(255,255,255,.08);background:rgba(0,0,0,.25);border-radius:14px}
.actions .count b{color:var(--accent-2)}
.linkbtn{color:#bcd4ff}
.empty{color:rgba(150,160,180,.55)}
.empty::before{color:rgba(138,180,255,.35)}
.footer a{color:rgba(140,170,230,.75)}

/* ================= 浅色淡绿主题 ================= */
:root{
  color-scheme:light;
  --bg:#eaf5ea;--bg-2:#e2f0e4;
  --surface:#ffffff;--surface-2:#f6fbf7;
  --ink:#1b2b22;--muted:#5f7568;
  --line:rgba(27,58,42,.13);--line-soft:rgba(27,58,42,.08);
  --accent:#2f8f5b;--accent-2:#1f6b43;--accent-deep:#175437;
  --gold:#2f8f5b;--gold-2:#1f6b43;--gold-deep:#175437;
  --green:#2f9c72;--amber:#b47f2a;--red:#c14b4b;
  --radius:16px;
  --shadow:0 18px 50px -34px rgba(23,64,42,.45),0 2px 6px -4px rgba(23,64,42,.2);
}
html{background:#eaf5ea}
body{
  color:#1b2b22;
  background:
    radial-gradient(900px 520px at 8% -10%, rgba(120,200,150,.30), transparent 62%),
    radial-gradient(760px 480px at 100% 0%, rgba(160,215,180,.24), transparent 58%),
    linear-gradient(180deg,#f0f8f0 0%,#e6f3e8 46%,#dcefe0 100%);
}
body::before{opacity:0}
body::after{background:radial-gradient(ellipse at 50% 0%,transparent 55%,rgba(120,160,135,.12) 100%)}
::selection{background:rgba(47,143,91,.22);color:#12211a}
a{color:#1f6b43}
.topbar{background:rgba(255,255,255,.82);border-bottom:1px solid rgba(27,58,42,.12);box-shadow:0 1px 0 rgba(255,255,255,.6) inset}
.topbar::before{background:linear-gradient(90deg,transparent,rgba(47,143,91,.35),transparent)}
.brand-mark{background:linear-gradient(135deg,#5fc38b,#2f8f5b 60%,#1f6b43);color:#f4fff8;box-shadow:0 8px 20px -10px rgba(47,143,91,.6)}
.brand-text b{color:#1b2b22}
.brand-text small{color:rgba(47,143,91,.75)}
.nav a{color:rgba(27,43,34,.62)}
.nav a:hover{color:#1f6b43;background:rgba(47,143,91,.09)}
.nav a.active{color:#fff;background:linear-gradient(135deg,#4bb87c,#2f8f5b);box-shadow:0 6px 16px -10px rgba(47,143,91,.8)}
.eyebrow{color:#2f8f5b}
.eyebrow::before{background:linear-gradient(90deg,transparent,#2f8f5b)}
.hero h1{background:linear-gradient(180deg,#1b2b22 0%,#25402f 55%,#2f8f5b 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero h1 em{background:linear-gradient(100deg,#2f9c72,#1f6b43);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{color:#5f7568}
.flow span{color:#3d5748;background:rgba(255,255,255,.72);border:1px solid rgba(27,58,42,.12)}
.flow i{color:rgba(47,143,91,.5)}
.panel{background:#ffffff;border:1px solid rgba(27,58,42,.1);box-shadow:var(--shadow)}
.panel::before{background:linear-gradient(90deg,transparent,rgba(47,143,91,.3),transparent)}
.search-field{border:1px solid rgba(27,58,42,.14);background:#fff;border-radius:14px;box-shadow:0 2px 6px -4px rgba(23,64,42,.3)}
.search-field input,.search input{color:#1b2b22;background:transparent}
.search-field input::placeholder,.search input::placeholder{color:rgba(95,117,104,.7)}
.search-field:focus-within{border-color:rgba(47,143,91,.55);box-shadow:0 0 0 3px rgba(47,143,91,.12)}
.search button,button[type=submit]{background:linear-gradient(135deg,#4bb87c,#2f8f5b 60%,#1f6b43);color:#fff;border-radius:12px;box-shadow:0 10px 24px -14px rgba(47,143,91,.7)}
.chip,.chip-btn{background:rgba(255,255,255,.75);border:1px solid rgba(27,58,42,.12);color:#3d5748}
.chip-btn{background:rgba(47,143,91,.1);border-color:rgba(47,143,91,.28);color:#1f6b43}
.chip-btn:hover{background:rgba(47,143,91,.18)}
.suggest-label{color:#5f7568}
.suggestion{background:#fff;border:1px solid rgba(27,58,42,.12);color:#2b4636}
.suggestion:hover{background:rgba(47,143,91,.1);border-color:rgba(47,143,91,.35)}
.stats-strip{color:#41604e}
.health-pill{background:rgba(255,255,255,.75);border:1px solid rgba(27,58,42,.12);color:#3d5748}
.health-pill.ok{color:#1f7a4f;border-color:rgba(47,156,114,.35);background:rgba(47,156,114,.08)}
.health-pill.bad{color:#a63c3c;border-color:rgba(193,75,75,.35);background:rgba(193,75,75,.07)}
.result{background:#fff;border:1px solid rgba(27,58,42,.1);border-radius:14px;box-shadow:0 2px 8px -6px rgba(23,64,42,.35)}
.result:hover{border-color:rgba(47,143,91,.4);box-shadow:0 14px 30px -22px rgba(23,64,42,.5)}
.result.selected{background:linear-gradient(180deg,#f2fbf4,#eaf6ec);border-color:rgba(47,143,91,.5);box-shadow:0 0 0 3px rgba(47,143,91,.1)}
.result-title{color:#16261d}
.result-zh{color:#2f6b4a}
.result input[type=checkbox]{border:1px solid rgba(47,143,91,.45);background:#fff}
.result input[type=checkbox]:checked{background:linear-gradient(135deg,#4bb87c,#2f8f5b);border-color:#2f8f5b}
.result input[type=checkbox]:checked::after{border-color:#fff}
.meta{color:#6a8074}
.badge{background:#f3f8f4;border:1px solid rgba(27,58,42,.1);color:#39543f}
.badge.good{background:rgba(47,156,114,.1);border-color:rgba(47,156,114,.28);color:#1f7a4f}
.badge.warn{background:rgba(180,127,42,.1);border-color:rgba(180,127,42,.26);color:#8f6420}
.badge.tag{background:rgba(47,143,91,.1);border-color:rgba(47,143,91,.24);color:#1f6b43}
.badge.hash{color:#7c9184}
.result::before{background:#cfdcd4}
.result[data-health="good"]::before{background:linear-gradient(180deg,#4bb87c,#2f8f5b)}
.result[data-health="warn"]::before{background:linear-gradient(180deg,#d9a24a,#b47f2a)}
.result[data-health="bad"]::before{background:linear-gradient(180deg,#d97b7b,#b44343)}
.seed-legend{margin-top:10px;font-size:12.5px;color:#7c9184;line-height:1.6}
.translate-hint{margin-top:10px;font-size:12.5px;color:#2f8f5b;line-height:1.6}
.translate-hint.hidden{display:none}
.seed-legend.hidden{display:none}
.actions{background:#f7fbf8;border:1px solid rgba(27,58,42,.1);border-radius:14px}
.actions .count{color:#5f7568}
.actions .count b{color:#1f6b43}
.linkbtn{color:#2f8f5b}
.job{background:#fff;border:1px solid rgba(27,58,42,.1);border-left-width:3px;border-radius:14px;box-shadow:0 2px 8px -6px rgba(23,64,42,.3)}
.job:hover{box-shadow:0 14px 30px -24px rgba(23,64,42,.5)}
.job-uploading,.job-queued{border-left-color:#b9c9be}
.job-downloading{border-left-color:#3f7fd6}
.job-awaiting_source{border-left-color:#c99235}
.job-processing{border-left-color:#7f63d9}
.job-completed{border-left-color:#2f9c72}
.job-failed{border-left-color:#c14b4b}
.job-title{color:#16261d}
.pill{background:#f1f6f2;color:#45604e;border:1px solid rgba(27,58,42,.12)}
.pill.downloading{background:rgba(63,127,214,.1);color:#2c5fa8;border-color:rgba(63,127,214,.28)}
.pill.awaiting_source{background:rgba(201,146,53,.12);color:#8a6118;border-color:rgba(201,146,53,.3)}
.pill.processing{background:rgba(127,99,217,.1);color:#5a41ad;border-color:rgba(127,99,217,.26)}
.pill.completed{background:rgba(47,156,114,.1);color:#1f7a4f;border-color:rgba(47,156,114,.3)}
.pill.failed{background:rgba(193,75,75,.1);color:#a63c3c;border-color:rgba(193,75,75,.28)}
.job-meta{color:#5f7568}
.job-error{color:#a63c3c;background:rgba(193,75,75,.07);border:1px solid rgba(193,75,75,.2)}
.job-hint{color:#8a6118;border-left:2px solid rgba(201,146,53,.55)}
.job-archive{color:#1f7a4f}
.job-usage{color:#8a6118}
.job-links a{background:rgba(47,143,91,.1);color:#1f6b43;border:1px solid rgba(47,143,91,.24);border-radius:8px}
.job-links a:hover{background:rgba(47,143,91,.18)}
.progress{background:rgba(27,58,42,.1)}
.progress>i{background:linear-gradient(90deg,#2f8f5b,#4bb87c)}
button.danger{background:rgba(193,75,75,.07);color:#a63c3c;border:1px solid rgba(193,75,75,.22)}
button.danger:hover{background:rgba(193,75,75,.14)}
button.danger.armed{background:#b44343;color:#fff}
button.retry{background:rgba(47,143,91,.1);color:#1f6b43;border:1px solid rgba(47,143,91,.26)}
button.retry:hover{background:rgba(47,143,91,.18)}
button.share{background:rgba(47,156,114,.1);color:#1f7a4f;border:1px solid rgba(47,156,114,.28)}
button.share:hover{background:rgba(47,156,114,.18)}
.modal{background:rgba(24,45,33,.42)}
.modal-card{background:#fff;border:1px solid rgba(27,58,42,.14);box-shadow:0 30px 70px -40px rgba(23,64,42,.6)}
.modal-title{color:#1b2b22}
.modal-close{color:rgba(27,43,34,.55)}
.modal-close:hover{color:#1b2b22}
.share-url{color:#1f6b43}
.share-hint{color:#5f7568}
.share-warning{color:#8a6118}
button.share-copy{background:#f1f6f2;color:#24382b;border:1px solid rgba(27,58,42,.14)}
button.share-copy:hover{background:#e7f1ea}
.empty{color:rgba(95,117,104,.7)}
.empty::before{color:rgba(47,143,91,.45)}
.upload-row input[type=file]{background:#f7fbf8;border:1px dashed rgba(47,143,91,.35);color:#5f7568}
.upload-row input[type=file]:hover{border-color:rgba(47,143,91,.65);background:rgba(47,143,91,.05)}
.upload-row input[type=file]::file-selector-button{background:rgba(47,143,91,.12);color:#1f6b43}
.upload-row input[type=text]{background:#fff;border:1px solid rgba(27,58,42,.14);color:#1b2b22}
.footer{color:rgba(95,117,104,.75)}
.footer a{color:#2f8f5b}
.pill::before{opacity:.75}

button{background:linear-gradient(135deg,#4bb87c,#2f8f5b 60%,#1f6b43);color:#fff;box-shadow:0 10px 24px -14px rgba(47,143,91,.6)}
button:hover{filter:brightness(1.04);box-shadow:0 14px 30px -14px rgba(47,143,91,.65)}
button.secondary{background:#f1f6f2;color:#24382b;border:1px solid rgba(27,58,42,.14);box-shadow:none}
button.secondary:hover{background:#e7f1ea;color:#1f6b43}
.search-field svg{color:rgba(47,143,91,.7)}
progress{background:rgba(27,58,42,.1)}
progress::-webkit-progress-bar{background:rgba(27,58,42,.1)}
progress::-webkit-progress-value{background:linear-gradient(90deg,#2f8f5b,#4bb87c)}
progress::-moz-progress-bar{background:linear-gradient(90deg,#2f8f5b,#4bb87c)}
.suggest-label{color:rgba(47,143,91,.75)}

/* 放大字号 */
.flow span{font-size:13px;padding:9px 15px;letter-spacing:.1em}
.flow i{font-size:14px}
.chip{font-size:13px;padding:7px 13px}
.eyebrow{font-size:11px}
.nav{font-size:14.5px}
.nav a{padding:10px 16px}
.brand-text b{font-size:18px}
.hero p{font-size:15.5px}
.stats-strip{font-size:14px}
.health-pill{font-size:12.5px;padding:4px 11px}
.result-title{font-size:16.5px}
.result-zh{font-size:14px}
.meta{font-size:12.5px}
.badge{font-size:12.5px;padding:4px 9px}
.job-title{font-size:17px}
.job-meta{font-size:13px}
.pill{font-size:11px}
.job-links{font-size:14px}
.job-hint,.job-archive,.job-usage,.job-error{font-size:13px}
.actions .count{font-size:13px}
.footer{font-size:12px}
.suggest-label{font-size:11px}
.suggestion{font-size:13px}
.search-field input{font-size:17px}
button{font-size:14px}
button.danger,button.retry,button.share{font-size:12px}
.share-url{font-size:16px}
.share-hint,.share-warning{font-size:14px}
.modal-title{font-size:16px}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style>
</head>
<body>
<header class="topbar">
  <div class="topbar-inner">
    <a class="brand" href="/">
      <span class="brand-mark">影</span>
      <span class="brand-text"><b>影片自动化</b><small>CINEMATIC AUTOMATION</small></span>
    </a>
    <nav class="nav">
      <a class="active" href="/">搜索</a>
      <a href="/setup">设置</a>
    </nav>
  </div>
</header>

<main>
  <section class="hero">
    <div class="hero-copy">
      <span class="eyebrow">CINEMATIC · MEDIA · AUTOMATION</span>
      <h1>让每一部影片<br><em>自带中文字幕</em></h1>
      <p>聚合索引器搜索片源，多选下载。自动识别语音、翻译为简体中文，再压制为可直接收藏的 MP4。你只需要选择，剩下的交给它。</p>
    </div>
    <div class="flow" aria-label="处理流程">
      <span>选片</span><i>—</i><span>下载</span><i>—</i><span>译制</span><i>—</i><span>成片</span>
    </div>
  </section>

  <div id="config-warning" class="warning hidden" aria-live="polite"></div>

  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>搜索影片资源</h2>
        <p class="hint">输入片名，或粘贴 magnet / .torrent 链接。中文搜不到时，试试日文原名或作品编号。</p>
      </div>
    </div>
    <form class="search" id="search-form">
      <div class="search-field">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>
        <input id="q" type="search" autocomplete="off" placeholder="片名，或 magnet:?xt=... / .torrent 链接" aria-label="搜索片名或磁力链接" autofocus>
      </div>
      <button type="submit" id="search-btn">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>
        搜索
      </button>
    </form>
    <div class="suggest-wrap hidden" id="suggest-wrap" aria-live="polite">
      <span class="suggest-label">关键词建议</span>
      <div class="suggestions" id="suggestions"></div>
    </div>
    <div class="stats-strip" id="stats-strip"></div>
    <div class="health-strip" id="health-strip"></div>
    <div class="chips">
      <button type="button" class="chip chip-btn" id="feed-btn">不知道下什么？看看最新</button>
      <button type="button" class="chip chip-btn" id="hot-btn">看看热门（按做种）</button>
      <button type="button" class="chip chip-btn" id="av-btn">AV 热门</button>
      <span class="chip">Prowlarr 聚合</span>
      <span class="chip">多选下载</span>
      <span class="chip">自动字幕</span>
      <span class="chip">自动压制</span>
    </div>
    <div class="status" id="status" aria-live="polite"></div>
    <div class="results" id="results"></div>
    <div class="translate-hint hidden" id="translate-hint">正在翻译标题…（模型较慢，约 10~20 秒；同系列第二次搜索会直接命中缓存）</div>
    <div class="seed-legend hidden" id="seed-legend">做种数来自索引器抓取，会偏高；真实可用做种以下载任务里的 seeds 为准。</div>
    <div class="actions hidden" id="actions">
      <span class="count">已选 <b id="count">0</b> 项</span>
      <button type="button" class="linkbtn" id="select-all">全选 / 取消全选</button>
      <button type="button" id="download-btn">开始下载</button>
    </div>
  </section>

  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>上传本地视频</h2>
        <p class="hint">没有合适的磁力或种子？直接上传，上传完成后自动生成中文字幕并压制。</p>
      </div>
    </div>
    <form id="upload-form">
      <div class="upload-row">
        <input id="upload-file" type="file" accept="video/*,.mkv,.ts" required aria-label="选择视频文件">
        <input id="upload-title" type="text" placeholder="片名（可选）" aria-label="片名">
        <button type="submit" id="upload-btn">上传并处理</button>
      </div>
    </form>
    <progress id="upload-progress" max="100" value="0" hidden></progress>
    <div class="status" id="upload-status" aria-live="polite"></div>
    <p class="hint" id="upload-limit">单个文件默认最多 8GB。</p>
  </section>

  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>最近任务</h2>
        <p class="hint">每 3 秒自动刷新；完成的任务会提供视频和字幕下载。</p>
      </div>
      <button type="button" class="secondary" id="refresh-btn">刷新</button>
    </div>
    <div class="status" id="jobs-status" aria-live="polite"></div>
    <div class="jobs" id="jobs"><div class="empty">暂无任务</div></div>
  </section>
</main>

<footer class="footer">
  <span>本地运行 · 数据保存在这台电脑</span>
  <a href="http://127.0.0.1:8096" target="_blank" rel="noreferrer">在线播放（Jellyfin）</a>
  <a href="/setup">配置服务 →</a>
</footer>

<div class="modal hidden" id="share-modal" role="dialog" aria-modal="true" aria-labelledby="share-title">
  <div class="modal-card">
    <button class="modal-close" id="share-close" aria-label="关闭">×</button>
    <div class="modal-title" id="share-title">手机接收</div>
    <div id="share-body"></div>
  </div>
</div>

<script>
const state = { results: [], selected: new Set(), query: "", jobsBusy: false, translateSeq: 0 };
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

async function api(path, options) {
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch (e) { /* non-JSON */ }
  if (!response.ok) throw new Error(data.detail || data.message || ("HTTP " + response.status));
  return data;
}

function setStatus(text, error) {
  const node = $("status");
  node.textContent = text || "";
  node.className = "status" + (error ? " error" : "");
}

function fmtSize(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return value + " B";
  const units = ["KB", "MB", "GB", "TB"];
  let size = value;
  for (const unit of units) {
    size /= 1024;
    if (size < 1024 || unit === "TB") return size.toFixed(1) + " " + unit;
  }
  return size.toFixed(1) + " TB";
}

function fmtEta(seconds) {
  const value = Number(seconds) || 0;
  if (!value) return "";
  if (value < 60) return value + " 秒";
  if (value < 3600) return Math.round(value / 60) + " 分钟";
  return Math.round(value / 360) / 10 + " 小时";
}

function updateCount() {
  $("count").textContent = state.selected.size;
  $("download-btn").disabled = state.selected.size === 0;
}

let suggestTimer = null;
let suggestSeq = 0;

function hideSuggestions() {
  suggestSeq += 1;
  clearTimeout(suggestTimer);
  const wrap = $("suggest-wrap");
  if (wrap) wrap.classList.add("hidden");
}

function setSuggestions(items) {
  const wrap = $("suggest-wrap");
  const box = $("suggestions");
  box.replaceChildren();
  const values = (items || []).filter(Boolean).slice(0, 6);
  if (!values.length) {
    wrap.classList.add("hidden");
    return;
  }
  values.forEach((value) => {
    const button = el("button", "suggestion", value);
    button.type = "button";
    button.title = "用这个关键词搜索";
    button.addEventListener("click", () => {
      $("q").value = value;
      hideSuggestions();
      runSearch();
    });
    box.appendChild(button);
  });
  wrap.classList.remove("hidden");
}

function scheduleSuggestions() {
  clearTimeout(suggestTimer);
  const query = $("q").value.trim();
  if (!query || !/[\u4e00-\u9fff]/.test(query)) {
    hideSuggestions();
    return;
  }
  const sequence = ++suggestSeq;
  const wrap = $("suggest-wrap");
  const box = $("suggestions");
  box.replaceChildren();
  box.appendChild(el("span", "suggest-loading", "正在生成关键词…"));
  wrap.classList.remove("hidden");
  suggestTimer = setTimeout(async () => {
    try {
      const data = await api("/api/suggest?q=" + encodeURIComponent(query));
      if (sequence !== suggestSeq) return;
      setSuggestions(data.suggestions || []);
    } catch (error) {
      if (sequence === suggestSeq) wrap.classList.add("hidden");
    }
  }, 750);
}

function resultTags(result) {
  const title = String(result.title || "").toUpperCase();
  const tags = [];
  if (/2160P|\b4K\b/.test(title)) tags.push("4K");
  else if (/1080P/.test(title)) tags.push("1080p");
  else if (/720P/.test(title)) tags.push("720p");
  if (/HEVC|H\.265|X265/.test(title)) tags.push("HEVC");
  if (/中文字幕|中字|CHS|CHT|_CH/.test(title)) tags.push("中字");
  if (/无码|無碼|UNCENSORED|REDUCING MOSAIC/.test(title)) tags.push("无码");
  if (/HDR/.test(title)) tags.push("HDR");
  return tags.slice(0, 4);
}

function renderResults() {
  const box = $("results");
  box.replaceChildren();
  state.results.forEach((result, index) => {
    const card = el("label", "result");
    card.classList.toggle("selected", state.selected.has(index));
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selected.has(index);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selected.add(index);
      else state.selected.delete(index);
      card.classList.toggle("selected", checkbox.checked);
      updateCount();
    });

    const body = el("div", "result-body");
    card.dataset.health = result.seeders_unknown ? "warn" : result.seeders >= 20 ? "good" : result.seeders >= 3 ? "warn" : "bad";
    body.appendChild(el("div", "result-title", result.title || "未命名资源"));
    if (result.title_zh) body.appendChild(el("div", "result-zh", "中文：" + result.title_zh));
    const meta = el("div", "meta");
    meta.appendChild(el("span", "badge", result.size_text || fmtSize(result.size)));
    if (result.seeders_unknown) meta.appendChild(el("span", "badge warn", "做种数未知"));
    else {
      const label = result.seeders >= 20 ? result.seeders + " 做种"
        : result.seeders >= 3 ? result.seeders + " 做种 · 偏慢"
        : result.seeders > 0 ? result.seeders + " 做种 · 很慢" : "无做种";
      const cls = result.seeders >= 20 ? "badge good" : "badge warn";
      const badge = el("span", cls, label);
      badge.title = "这是索引器自己抓的统计，常含已下线节点；真实可连做种看任务卡里的 seeds";
      meta.appendChild(badge);
    }
    resultTags(result).forEach((tag) => meta.appendChild(el("span", "badge tag", tag)));
    if (result.indexer) meta.appendChild(el("span", "badge", result.indexer));
    if (Number(result.duplicates) > 0) {
      const dup = el("span", "badge tag", "已合并 " + (Number(result.duplicates) + 1) + " 个同资源");
      if (Array.isArray(result.also_from) && result.also_from.length) {
        dup.title = "其它来源：" + result.also_from.join("、");
      }
      meta.appendChild(dup);
    }
    body.appendChild(meta);

    card.appendChild(checkbox);
    card.appendChild(body);
    box.appendChild(card);
  });
  $("actions").classList.toggle("hidden", state.results.length === 0);
  const legend = $("seed-legend");
  if (legend) legend.classList.toggle("hidden", state.results.length === 0);
  updateCount();
}

async function translateResults() {
  const seq = ++state.translateSeq;
  const titles = state.results.map((result) => result.title).filter(Boolean);
  if (!titles.length) return;
  const hint = $("translate-hint");
  if (hint) hint.classList.remove("hidden");
  try {
    const data = await api("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ titles: titles }),
    });
    if (seq !== state.translateSeq) return;
    const map = data.translations || {};
    let changed = false;
    state.results.forEach((result) => {
      const zh = map[result.title];
      if (zh && zh !== result.title && !result.title_zh) {
        result.title_zh = zh;
        changed = true;
      }
    });
    if (changed) renderResults();
  } catch (error) {
    /* 翻译只是锦上添花，失败时保留原标题 */
  } finally {
    const node = $("translate-hint");
    if (node) node.classList.add("hidden");
  }
}

async function loadFeed(mode) {
  const sort = mode === "hot" ? "seeders" : "date";
  const button = mode === "hot" ? $("hot-btn") : $("feed-btn");
  if (!button) return;
  button.disabled = true;
  setStatus(mode === "hot" ? "正在拉取当前做种最多的资源…" : "正在拉取各站最新资源…");
  try {
    const suffix = mode === "av" ? "&source=av" : "";
    const data = await api("/api/feed?limit=40&sort=" + sort + suffix);
    state.results = data.results || [];
    state.selected.clear();
    state.query = "";
    renderResults();
    translateResults();
    if (state.results.length) {
      setStatus(
        mode === "av"
          ? "成人站当前做种最多的 " + state.results.length + " 条（索引器统计，真实性看 qBittorrent）"
          : mode === "hot"
          ? "当前做种最多的 " + state.results.length + " 条（索引器统计，实际做种以 qBittorrent 为准）"
          : "各站最新 " + state.results.length + " 条（按发布时间倒序），勾选后可下载"
      );
    } else {
      setStatus("没有拿到最新资源，稍后再试");
    }
  } catch (error) {
    setStatus("获取最新资源失败：" + error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function loadStats() {
  try {
    const stats = await api("/api/stats");
    const symbol = stats.currency === "CNY" ? "¥" : "$";
    const tokens = Number(stats.tokens || 0).toLocaleString("en-US");
    $("stats-strip").textContent =
      "共 " + stats.total + " 部 · 本周 " + stats.week + " 部 · 完成 " + stats.completed +
      " · 失败 " + stats.failed + " · 翻译 " + tokens + " tokens · 约 " + symbol + Number(stats.cost || 0).toFixed(3);
  } catch (error) { /* 统计失败不影响主流程 */ }
}

async function loadHealth() {
  try {
    const data = await api("/api/health/status");
    const box = $("health-strip");
    if (!box) return;
    box.replaceChildren(
      ...(data.items || []).map((item) =>
        el("span", "health-pill " + (item.ok ? "ok" : "bad"), item.name + " · " + (item.detail || ""))
      )
    );
  } catch (error) { /* 健康检查失败忽略 */ }
}

async function runSearch(event) {
  if (event) event.preventDefault();
  const query = $("q").value.trim();
  if (!query) return;
  state.query = query;
  state.results = [];
  state.selected.clear();
  $("results").replaceChildren();
  $("actions").classList.add("hidden");
  setStatus("搜索中…");
  $("search-btn").disabled = true;
  try {
    const data = await api("/api/search?q=" + encodeURIComponent(query) + "&limit=50");
    state.results = data.results || [];
    renderResults();
    translateResults();
    if (!state.results.length) setStatus("没有找到匹配结果。试试英文名、日文原名或作品编号，也可以直接粘贴磁力链接；当前索引器可能没有收录这部片。");
    else setStatus("找到 " + state.results.length + " 个结果，勾选后点“开始下载”。");
  } catch (error) {
    setStatus("搜索失败：" + error.message, true);
  } finally {
    $("search-btn").disabled = false;
  }
}

async function startDownload() {
  const items = state.results.filter((_, index) => state.selected.has(index));
  if (!items.length) return;
  const button = $("download-btn");
  button.disabled = true;
  setStatus("正在创建下载任务…");
  try {
    const data = await api("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: items, title: state.query })
    });
    const jobs = data.jobs || [];
    const failed = jobs.filter((job) => job.status === "failed").length;
    const accepted = jobs.length - failed;
    setStatus("已创建 " + accepted + " 个下载任务" + (failed ? "，" + failed + " 个失败，见任务列表。" : "。"));
    state.selected.clear();
    renderResults();
    refreshJobs();
  } catch (error) {
    setStatus("创建任务失败：" + error.message, true);
  } finally {
    button.disabled = false;
  }
}

const STATUS_TEXT = {
  uploading: "上传中",
  queued: "排队中",
  downloading: "下载中",
  awaiting_source: "等待处理",
  processing: "处理中",
  completed: "已完成",
  failed: "失败"
};

const STAGE_TEXT = {
  transcribing: "识别语音",
  on_screen: "识别画面文字",
  translating: "翻译字幕",
  burning: "压制视频",
  copying: "整理文件",
  done: "完成"
};

function jobCard(job) {
  const card = el("div", "job job-" + (job.status || "unknown"));
  const head = el("div", "job-head");
  head.appendChild(el("div", "job-title", job.title || job.id));
  head.appendChild(el("span", "pill " + (job.status || ""), STATUS_TEXT[job.status] || job.status || "未知"));
  card.appendChild(head);

  const download = job.download || {};
  const meta = el("div", "job-meta");
  meta.appendChild(el("span", null, job.id));
  if (download.progress !== undefined && job.status === "downloading") {
    const pct = (Number(download.progress) || 0) * 100;
    meta.appendChild(el("span", null, (pct < 1 && pct > 0 ? pct.toFixed(2) : Math.round(pct)) + "%"));
    if (download.size) {
      meta.appendChild(el("span", null, fmtSize(download.completed || 0) + " / " + fmtSize(download.size)));
    }
    meta.appendChild(el("span", null, download.dlspeed ? fmtSize(download.dlspeed) + "/s" : "0 B/s"));
    const eta = fmtEta(download.eta);
    if (eta) meta.appendChild(el("span", null, "剩余 " + eta));
    if (download.seeds_total !== undefined) {
      meta.appendChild(el("span", null, "做种 " + (download.seeds || 0) + "/" + (download.seeds_total || 0)));
    }
  }
  if (job.status === "processing") {
    const stage = job.stage || {};
    const label = STAGE_TEXT[stage.name] || "处理中";
    const percent = Number(stage.percent);
    meta.appendChild(el("span", null, label + (Number.isFinite(percent) ? " " + Math.round(percent) + "%" : "")));
    if (stage.detail) meta.appendChild(el("span", null, stage.detail));
  }
  if (job.source && job.source.indexer) meta.appendChild(el("span", null, job.source.indexer));
  card.appendChild(meta);

  if (job.status === "queued" && download.state === "metaDL") {
    card.appendChild(el("div", "job-hint", "正在向 peers 获取种子信息（metaDL）：还没连上做种，可能这个资源没人做种或磁力缺 tracker。等 10 分钟没动静就换一个做种多的版本。"));
  }
  if (job.status === "downloading" && download.slow) {
    card.appendChild(el("div", "job-hint", "这个种子长时间没速度，系统已尝试自动换成做种更多的版本；如果还慢，建议删掉换一个。"));
  }
  if (job.status === "downloading" && Number(download.progress) < 0.001 && !download.seeds_total) {
    card.appendChild(el("div", "job-hint", "还连不上做种：这个种子可能没人做种，建议换一个做种数更多的结果，或稍等 DHT 找到节点。"));
  }

  if (job.status === "downloading" || job.status === "queued") {
    const progress = el("div", "progress");
    const bar = document.createElement("i");
    bar.style.width = Math.round((Number(download.progress) || 0) * 100) + "%";
    progress.appendChild(bar);
    card.appendChild(progress);
  } else if (job.status === "processing") {
    const stage = job.stage || {};
    const percent = Number(stage.percent);
    const progress = el("div", "progress" + (Number.isFinite(percent) ? "" : " indeterminate"));
    const bar = document.createElement("i");
    if (Number.isFinite(percent)) bar.style.width = Math.max(2, Math.min(100, percent)) + "%";
    progress.appendChild(bar);
    card.appendChild(progress);
  }

  if (job.error) card.appendChild(el("div", "job-error", job.error));

  if (job.status === "completed") {
    const links = el("div", "job-links");
    const video = el("a", null, "下载视频");
    video.href = "/download/" + encodeURIComponent(job.id);
    links.appendChild(video);
    if (job.subtitle_file) {
      const subtitle = el("a", null, "下载字幕");
      subtitle.href = "/subtitle/" + encodeURIComponent(job.id);
      links.appendChild(subtitle);
    }
    card.appendChild(links);
    if (job.archive_dir) {
      card.appendChild(el("div", "job-archive", "已自动保存到 " + job.archive_dir));
    }
    const usage = job.translation_usage;
    if (usage && Number(usage.total_tokens) > 0) {
      const fmt = (value) => Number(value || 0).toLocaleString("en-US");
      const symbol = usage.currency === "CNY" ? "¥" : "$";
      let text = "翻译用量 " + fmt(usage.total_tokens) + " tokens（输入 " + fmt(usage.prompt_tokens) + " / 输出 " + fmt(usage.completion_tokens);
      if (Number(usage.cached_tokens) > 0) text += "，缓存 " + fmt(usage.cached_tokens);
      text += "）";
      if (usage.priced) text += " · 约 " + symbol + Number(usage.cost).toFixed(4);
      card.appendChild(el("div", "job-usage", text));
    }
  }

  const actions = el("div", "job-actions");
  if (job.status === "completed") {
    const share = el("button", "share", "手机接收");
    share.type = "button";
    share.addEventListener("click", () => openShare(job));
    actions.appendChild(share);
  }
  if (job.status === "failed") {
    const retry = el("button", "retry", "重试");
    retry.type = "button";
    retry.addEventListener("click", async () => {
      retry.disabled = true;
      retry.textContent = "重试中…";
      try {
        await api("/api/jobs/" + encodeURIComponent(job.id) + "/retry", { method: "POST" });
        setJobsStatus("已重新排队：" + job.id);
        await refreshJobs();
      } catch (error) {
        setJobsStatus("重试失败：" + error.message, true);
        retry.disabled = false;
        retry.textContent = "重试";
      }
    });
    actions.appendChild(retry);
  }
  const remove = el("button", "danger", "删除");
  remove.type = "button";
  let armed = false;
  let armTimer = null;
  remove.addEventListener("click", () => {
    if (!armed) {
      armed = true;
      remove.textContent = "确认删除";
      remove.classList.add("armed");
      armTimer = setTimeout(() => {
        armed = false;
        remove.textContent = "删除";
        remove.classList.remove("armed");
      }, 4000);
      return;
    }
    clearTimeout(armTimer);
    deleteJob(job, remove);
  });
  actions.appendChild(remove);
  card.appendChild(actions);
  return card;
}

function closeShare() {
  const modal = $("share-modal");
  if (modal) modal.classList.add("hidden");
}

async function openShare(job) {
  const modal = $("share-modal");
  const body = $("share-body");
  if (!modal || !body) return;
  $("share-title").textContent = job.title ? "手机接收 · " + job.title.slice(0, 16) : "手机接收";
  body.replaceChildren(el("div", "share-hint", "正在生成二维码…"));
  modal.classList.remove("hidden");
  try {
    const info = await api("/api/share/" + encodeURIComponent(job.id));
    const image = document.createElement("img");
    image.className = "share-qr";
    image.alt = "手机扫码下载";
    image.src = "/api/qr/" + encodeURIComponent(job.id) + "?t=" + Date.now();
    const address = el("div", "share-url", info.short || info.url);
    const hint = el("div", "share-hint",
      "手机连同一个 Wi-Fi，在浏览器直接输入上面这个短地址就能下载（不用扫码、不用登录）；扫码用的是完整链接。");
    const copy = el("button", "share-copy", "复制地址");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(info.url);
        copy.textContent = "已复制";
      } catch (error) {
        copy.textContent = "复制失败，手动选中地址";
      }
    });
    const full = el("div", "share-hint", "");
    full.textContent = "完整链接：" + info.url;
    full.style.wordBreak = "break-all";
    full.style.fontSize = "12px";
    full.style.opacity = ".75";
    const children = [image, address, hint, full];
    if (info.warning) children.push(el("div", "share-warning", info.warning));
    children.push(copy);
    body.replaceChildren(...children);
  } catch (error) {
    body.replaceChildren(el("div", "share-warning", "生成失败：" + error.message));
  }
}

function setJobsStatus(text, error) {
  const node = $("jobs-status");
  if (!node) return;
  node.textContent = text || "";
  node.className = "status" + (error ? " error" : "");
}

async function deleteJob(job, button) {
  button.disabled = true;
  button.textContent = "删除中…";
  try {
    await api("/api/jobs/" + encodeURIComponent(job.id), { method: "DELETE" });
    setJobsStatus("已删除：" + job.id);
    await refreshJobs();
  } catch (error) {
    setJobsStatus("删除失败：" + error.message, true);
    button.disabled = false;
    button.textContent = "删除";
    button.classList.remove("armed");
  }
}

async function refreshJobs() {
  if (state.jobsBusy) return;
  state.jobsBusy = true;
  try {
    const jobs = await api("/jobs");
    const box = $("jobs");
    box.replaceChildren();
    if (!jobs.length) {
      box.appendChild(el("div", "empty", "暂无任务"));
    } else {
      jobs.slice(0, 30).forEach((job) => box.appendChild(jobCard(job)));
    }
  } catch (error) {
    /* Keep the previous list if the worker is restarting. */
  } finally {
    state.jobsBusy = false;
  }
}

function setUploadStatus(text, error) {
  const node = $("upload-status");
  node.textContent = text || "";
  node.className = "status" + (error ? " error" : "");
}

async function uploadVideo(file, title) {
  const button = $("upload-btn");
  const progress = $("upload-progress");
  const formData = new FormData();
  formData.append("file", file);
  if (title) formData.append("title", title);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");
  xhr.withCredentials = true;
  progress.hidden = false;
  progress.value = 0;
  button.disabled = true;
  setUploadStatus("正在上传 " + file.name + "…");
  xhr.upload.addEventListener("progress", (event) => {
    if (event.lengthComputable && event.total) {
      progress.value = Math.round((event.loaded / event.total) * 100);
      setUploadStatus("正在上传 " + progress.value + "%");
    }
  });
  xhr.addEventListener("load", () => {
    let data = {};
    try { data = JSON.parse(xhr.responseText || "{}"); } catch (error) { /* ignore */ }
    if (xhr.status >= 200 && xhr.status < 300) {
      const job = data.job || {};
      progress.value = 100;
      setUploadStatus("上传完成，任务已创建：" + (job.id || ""));
      $("upload-file").value = "";
      $("upload-title").value = "";
      refreshJobs();
    } else {
      setUploadStatus("上传失败：" + (data.detail || ("HTTP " + xhr.status)), true);
    }
    button.disabled = false;
  });
  xhr.addEventListener("error", () => {
    setUploadStatus("上传失败：网络错误", true);
    button.disabled = false;
  });
  xhr.send(formData);
}

async function checkConfig() {
  try {
    const status = await api("/api/config/status");
    if (status.max_upload_gb) {
      $("upload-limit").textContent = "单个文件最多 " + status.max_upload_gb + "GB。";
    }
    const missing = [];
    if (!status.prowlarr) missing.push("Prowlarr");
    if (!status.qbittorrent) missing.push("qBittorrent 地址");
    else if (!status.qbittorrent_password) missing.push("qBittorrent 密码");
    if (missing.length) {
      const warning = $("config-warning");
      warning.textContent = "还没有配置 " + missing.join(" 和 ") + "。请先到设置页填写，否则搜索和下载不可用。";
      const link = el("a", null, " 去设置 →");
      link.href = "/setup";
      warning.appendChild(link);
      warning.classList.remove("hidden");
    }
  } catch (error) { /* ignore */ }
}

$("upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const file = $("upload-file").files[0];
  if (!file) {
    setUploadStatus("请先选择一个视频文件", true);
    return;
  }
  uploadVideo(file, $("upload-title").value.trim());
});
$("q").addEventListener("input", scheduleSuggestions);
$("search-form").addEventListener("submit", runSearch);
$("download-btn").addEventListener("click", startDownload);
$("feed-btn").addEventListener("click", () => loadFeed("date"));
$("hot-btn").addEventListener("click", () => loadFeed("hot"));
$("av-btn").addEventListener("click", () => loadFeed("av"));
$("refresh-btn").addEventListener("click", refreshJobs);
$("select-all").addEventListener("click", () => {
  if (state.selected.size === state.results.length) state.selected.clear();
  else state.results.forEach((_, index) => state.selected.add(index));
  renderResults();
});

$("share-close").addEventListener("click", closeShare);
$("share-modal").addEventListener("click", (event) => {
  if (event.target.id === "share-modal") closeShare();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeShare();
});

checkConfig();
refreshJobs();
loadStats();
loadHealth();
setInterval(() => { if (!document.hidden) refreshJobs(); }, 3000);
setInterval(() => { if (!document.hidden) { loadStats(); loadHealth(); } }, 60000);
</script>
</body>
</html>
"""


def search_page() -> str:
    return SEARCH_PAGE
