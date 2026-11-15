param(
    [Parameter(Mandatory=$true)][ValidateSet('Register', 'Unregister', 'Status')][string]$Action,
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$AppId,
    [string]$Target = '',
    [string]$Arguments = '',
    [string]$Icon = '',
    [string]$WorkingDirectory = ''
)
# Creates, reads or removes exactly one .lnk carrying System.AppUserModel.ID. Windows uses that
# shortcut to name toasts from an unpackaged program. Nothing else on the system is touched.
# Output: one JSON object on stdout. Exit 0 on success, 2 on refusal or failure.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

public static class GuardShortcut {
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder file, int max, IntPtr data, uint flags);
        void GetIDList(out IntPtr list);
        void SetIDList(IntPtr list);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder name, int max);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder dir, int max);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string dir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder args, int max);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
        void GetHotkey(out short key);
        void SetHotkey(short key);
        void GetShowCmd(out int cmd);
        void SetShowCmd(int cmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int max, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        void Resolve(IntPtr hwnd, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct PropertyKey { public Guid fmtid; public uint pid; }

    [StructLayout(LayoutKind.Explicit)]
    struct PropVariant {
        [FieldOffset(0)] public ushort vt;
        [FieldOffset(8)] public IntPtr pointer;
        [FieldOffset(8)] public long padding;
        [FieldOffset(16)] public long padding2;
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        void GetCount(out uint count);
        void GetAt(uint index, out PropertyKey key);
        void GetValue(ref PropertyKey key, out PropVariant value);
        void SetValue(ref PropertyKey key, ref PropVariant value);
        void Commit();
    }

    [DllImport("ole32.dll")] static extern int PropVariantClear(ref PropVariant value);

    static PropertyKey AppIdKey() {
        PropertyKey key = new PropertyKey();
        key.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
        key.pid = 5;
        return key;
    }

    static object NewLink() {
        return Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
    }

    public static void Create(string path, string target, string args, string icon, string workdir, string appId) {
        object link = NewLink();
        IShellLinkW shell = (IShellLinkW)link;
        shell.SetPath(target);
        shell.SetArguments(args);
        if (!String.IsNullOrEmpty(workdir)) shell.SetWorkingDirectory(workdir);
        if (!String.IsNullOrEmpty(icon)) shell.SetIconLocation(icon, 0);
        shell.SetDescription("CCGuard");
        IPropertyStore store = (IPropertyStore)link;
        PropertyKey key = AppIdKey();
        PropVariant value = new PropVariant();
        value.vt = 31; // VT_LPWSTR
        value.pointer = Marshal.StringToCoTaskMemUni(appId);
        try {
            store.SetValue(ref key, ref value);
            store.Commit();
        } finally {
            Marshal.FreeCoTaskMem(value.pointer);
        }
        ((IPersistFile)link).Save(path, true);
    }

    public static string ReadAppId(string path) {
        object link = NewLink();
        ((IPersistFile)link).Load(path, 0);
        IPropertyStore store = (IPropertyStore)link;
        PropertyKey key = AppIdKey();
        PropVariant value;
        store.GetValue(ref key, out value);
        try {
            return value.vt == 31 ? Marshal.PtrToStringUni(value.pointer) : null;
        } finally {
            PropVariantClear(ref value);
        }
    }
}
'@

function Out-Result($object, [int]$code = 0) {
    $object | ConvertTo-Json -Compress
    exit $code
}

try {
    $exists = Test-Path -LiteralPath $Path -PathType Leaf
    $current = $null
    if ($exists) { $current = [GuardShortcut]::ReadAppId($Path) }
    switch ($Action) {
        'Status' {
            Out-Result @{ registered = ($exists -and $current -eq $AppId); path = $Path; exists = $exists }
        }
        'Register' {
            if ($exists -and $current -ne $AppId) {
                Out-Result @{ error = '同名快捷方式已存在且不属于 CCGuard，未覆盖：' + $Path } 2
            }
            if (-not $Target -or -not (Test-Path -LiteralPath $Target -PathType Leaf)) {
                Out-Result @{ error = '启动程序不存在：' + $Target } 2
            }
            $folder = Split-Path -Parent $Path
            if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Path $folder | Out-Null }
            [GuardShortcut]::Create($Path, $Target, $Arguments, $Icon, $WorkingDirectory, $AppId)
            if ([GuardShortcut]::ReadAppId($Path) -ne $AppId) {
                Remove-Item -LiteralPath $Path -Force
                Out-Result @{ error = '快捷方式写入后读回的程序身份不一致，已删除。' } 2
            }
            Out-Result @{ registered = $true; path = $Path }
        }
        'Unregister' {
            if (-not $exists) { Out-Result @{ removed = $false; path = $Path } }
            if ($current -ne $AppId) {
                Out-Result @{ error = '同名快捷方式不属于 CCGuard，未删除：' + $Path } 2
            }
            Remove-Item -LiteralPath $Path -Force
            Out-Result @{ removed = $true; path = $Path }
        }
    }
} catch {
    Out-Result @{ error = $_.Exception.Message } 2
}
