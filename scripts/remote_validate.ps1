<#
Run `funscript-gen validate` on the Windows test host (the maintainer's private test host) without taking the machine's total CPU use,
the owner's own programs included, over -MaxPct.

The job count alone cannot do it: one generate already keeps all 16 threads busy at times (PyAV decoding, OpenCV
and onnxruntime start their own threads; 1 job x 4 flow workers had a median of 96 %). So the runs are confined to
some of the logical processors with the processor affinity, which child processes inherit, and run at below-normal
priority. Before starting it gives them what the owner leaves free under the cap, and every -Interval seconds it
takes 2 away while the total is within 5 % of the cap and gives 1 back while 2 more would stay below that. The job
count follows from the processors at the start (one per 4, rounded up).

The total is Task Manager's number, "% Processor Utility" (capped at 100): it counts the boost clock and reads
higher than "% Processor Time" (idle 19-29 % against 15 % on this host).

usage (in C:\Lab\funscript-gen\repo, after `. ..\env.ps1`):
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remote_validate.ps1 -Name RUN `
    -Validate "-c default --clips B03,H01" [-MaxPct 80] [-Jobs N]
The output of validate goes to out\runs\RUN.log; the CPU decisions are printed.
Other long jobs (experiment scripts) go through it too: -Run "scripts\x.py ARGS" runs the venv's python with those
arguments instead of validate (-Jobs is then unused), with the same cap and log.
#>
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Validate = "-c default",
    [string]$Run = "",
    [int]$MaxPct = 80,
    [int]$Jobs = 0,
    [int]$Interval = 5
)
$ErrorActionPreference = "Stop"

$cores = [Environment]::ProcessorCount
$least = 2
$most = [math]::Max($least, [math]::Floor($cores * $MaxPct / 100))
$boost = 1.5  # a busy processor reads up to ~1.5x its share of "% Processor Utility" with the boost clock
$room = $boost * 2 * 100 / $cores  # 2 more processors
$aim = $MaxPct - 5  # a new clip starting, or the owner, can add several % within one sample

function Get-TotalCpu([int]$Seconds) {
    for ($try = 0; ; $try++) {
        try {
            $c = Get-Counter "\Processor Information(_Total)\% Processor Utility" -SampleInterval $Seconds -MaxSamples 1
            return [math]::Min(100, $c.CounterSamples[0].CookedValue)
        } catch {
            if ($try -ge 3) { throw }  # it now and then fails with "negative denominator"; the next sample is fine
        }
    }
}

function Get-Tree([int]$Root) {
    $all = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId
    $ids = @($Root)
    $grew = $true
    while ($grew) {
        $more = @($all | Where-Object { $ids -contains $_.ParentProcessId -and $ids -notcontains $_.ProcessId } |
            ForEach-Object { [int]$_.ProcessId })
        $grew = $more.Count -gt 0
        $ids += $more
    }
    $ids
}

function Set-Cpus([int]$Root, [int]$Count) {
    $mask = [IntPtr][int64]([math]::Pow(2, $Count) - 1)
    [Diagnostics.Process]::GetCurrentProcess().ProcessorAffinity = $mask  # so later children start with it
    foreach ($id in Get-Tree $Root) {
        try { (Get-Process -Id $id).ProcessorAffinity = $mask } catch { }  # it may have just exited
    }
}

# What the owner is using now decides the starting share.
$owner = Get-TotalCpu 5
$cpus = [math]::Max($least, [math]::Min($most, [math]::Floor($cores * ($aim - $owner) / 100 / $boost)))
if ($Jobs -le 0) { $Jobs = [math]::Ceiling($cpus / 4) }
"owner {0:N0} %: {1} of {2} logical processors, {3} jobs" -f $owner, $cpus, $cores, $Jobs

$me = [Diagnostics.Process]::GetCurrentProcess()
$me.PriorityClass = "BelowNormal"  # inherited by the children
$me.ProcessorAffinity = [IntPtr][int64]([math]::Pow(2, $cpus) - 1)

$log = "out\runs\$Name.log"
New-Item -ItemType Directory -Force out\runs | Out-Null
$argv = @("-m", "funscript_gen.cli", "validate", $Name, "-j", $Jobs) + ($Validate -split "\s+" | Where-Object { $_ })
if ($Run) { $argv = $Run -split "\s+" | Where-Object { $_ } }
$proc = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList $argv -PassThru -NoNewWindow `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err"
$null = $proc.Handle  # keeps the exit code readable after it exits

$samples = @()
$t0 = Get-Date
try {
    while (-not $proc.HasExited) {
        $total = Get-TotalCpu $Interval
        if ($proc.HasExited) { break }
        $samples += $total
        $new = $cpus
        if ($total -gt $aim) { $new = [math]::Max($least, $cpus - 2) }
        elseif ($total + $room -lt $aim) { $new = [math]::Min($most, $cpus + 1) }
        if ($new -ne $cpus) {
            Set-Cpus $proc.Id $new
            "{0:N0} s: total {1:N0} %, {2} -> {3} logical processors" -f ((Get-Date) - $t0).TotalSeconds, $total, $cpus, $new
            $cpus = $new
        }
    }
} finally {
    # Nothing may go on running without the cap: if this script stops (an error, Ctrl+C), stop the jobs too.
    if (-not $proc.HasExited) { taskkill /T /F /PID $proc.Id | Out-Null }
}
$proc.WaitForExit()

$sorted = $samples | Sort-Object
$n = $sorted.Count
if ($n) {
    "total CPU over {0:N0} s: mean {1:N0} %, 90th percentile {2:N0} %, max {3:N0} %, over {4} %: {5} of {6} samples" -f `
        ((Get-Date) - $t0).TotalSeconds, ($samples | Measure-Object -Average).Average, $sorted[[int][math]::Floor(($n - 1) * 0.9)],
        $sorted[$n - 1], $MaxPct, @($samples | Where-Object { $_ -gt $MaxPct }).Count, $n
}
Get-Content $log -Tail 40
exit $proc.ExitCode
