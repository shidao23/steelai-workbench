<#
.SYNOPSIS
    SteelAI Workbench 本机实例健康探测（Windows 启动器专用）。

.DESCRIPTION
    只探测 http://127.0.0.1:<Port>/_stcore/health 是否返回 HTTP 200，用于判断
    SteelAI 是否已经在运行。exit 0 = 已在运行；exit 1 = 未运行或无法确认。

    该请求显式绕过代理：Windows PowerShell 5.1 的 Invoke-WebRequest 没有
    -NoProxy 参数，所以这里直接使用 System.Net.WebRequest，并只把本次请求的
    Proxy 置空。系统 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY 既不会被
    读取，也不会被修改或持久化，其他网络请求的代理行为不受影响。

    探针只访问 127.0.0.1，不访问外部网络，也不启动任何进程。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [int]$Port,

    [int]$TimeoutSeconds = 2
)

$exitNotRunning = 1

if ($Port -lt 1 -or $Port -gt 65535) {
    # 无效端口不能当作"已在运行"，交由启动器进入正常启动路径。
    exit $exitNotRunning
}

try {
    $request = [System.Net.WebRequest]::Create("http://127.0.0.1:$Port/_stcore/health")
    $request.Method = 'GET'
    $request.Timeout = $TimeoutSeconds * 1000
    $request.ReadWriteTimeout = $TimeoutSeconds * 1000
    # 仅对本次 loopback 请求禁用代理；不修改任何全局或环境代理设置。
    $request.Proxy = $null

    $response = $null
    try {
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -eq 200) {
            exit 0
        }
    }
    finally {
        if ($null -ne $response) {
            $response.Close()
            $response.Dispose()
        }
    }
}
catch {
    exit $exitNotRunning
}

exit $exitNotRunning
