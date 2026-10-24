# 待機中のアプリの物理メモリをページファイルへ退避する(閉じない・データは失われない)。LLM/シミュレーター実行前に使う。
# 対象: ブラウザ、ChatGPTアプリ、WebView2、Eagle、Zoom など。使うときに読み戻すので、触った直後だけ少し重くなる。
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class WS { [DllImport("psapi.dll")] public static extern int EmptyWorkingSet(IntPtr h); }'
function FreeGB { [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2) }
"before free GB: " + (FreeGB)
$names = 'brave','ChatGPT','msedgewebview2','Eagle','msedge','Zoom','chrome'
$before = (Get-Process $names -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum/1GB
$n = 0
Get-Process $names -ErrorAction SilentlyContinue | ForEach-Object { try { if ([WS]::EmptyWorkingSet($_.Handle) -ne 0) { $n++ } } catch {} }
Start-Sleep 6
$after = (Get-Process $names -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum/1GB
"trimmed processes: $n"
"target working set GB: {0:N2} -> {1:N2}" -f $before, $after
"after free GB: " + (FreeGB)
