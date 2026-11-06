// Launcher of the Windows portable build, compiled twice by build.ps1 with the .NET Framework's csc.exe:
//   funscript-gen.exe  (/target:exe)                 the CLI: runtime\python.exe -m funscript_gen.cli <arguments>
//   FunscriptGen.exe   (/target:winexe /define:GUI)  the app: runtime\pythonw.exe -m funscript_gen.cli app <arguments>
// Both find runtime\ next to themselves, so the folder can be moved or renamed, and point FUNSCRIPT_GEN_HOME and
// TEMP at data\, so nothing is written outside the folder, and FUNSCRIPT_GEN_LANG_DIR at lang\ (the language packs: a
// .toml file added there shows up in the language list). Python runs isolated (-I: no PYTHON* variables, no user
// site-packages) in UTF-8 mode. The launcher's own messages come before any language pack is loaded: Chinese on a
// Chinese system, English otherwise.
using System;
using System.Diagnostics;
using System.IO;
#if GUI
using System.Windows.Forms;
#endif

static class Launcher
{
    // The command line after the program's own name, passed on unchanged (quotes included).
    static string Arguments()
    {
        string line = Environment.CommandLine;
        int i = 0;
        if (line.StartsWith("\""))
        {
            i = line.IndexOf('"', 1);
            i = i < 0 ? line.Length : i + 1;
        }
        else
        {
            while (i < line.Length && !char.IsWhiteSpace(line[i])) i++;
        }
        return line.Substring(i).TrimStart();
    }

    static string Tr(string zh, string en)
    {
        return System.Globalization.CultureInfo.CurrentUICulture.Name.StartsWith("zh", StringComparison.OrdinalIgnoreCase) ? zh : en;
    }

    static void Fail(string message)
    {
#if GUI
        MessageBox.Show(message, "funscript-gen", MessageBoxButtons.OK, MessageBoxIcon.Error);
#else
        Console.Error.WriteLine(message);
#endif
    }

    [STAThread]
    static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
#if GUI
        string python = Path.Combine(root, "runtime", "pythonw.exe");
        string command = "app";
#else
        string python = Path.Combine(root, "runtime", "python.exe");
        string command = "";
#endif
        if (!File.Exists(python))
        {
            Fail(Tr("找不到 " + python + "\n請把整個資料夾解壓縮後再執行，不要只複製執行檔。",
                    "Cannot find " + python + "\nExtract the whole folder before running it; do not copy only the executable."));
            return 1;
        }
        string data = Path.Combine(root, "data");
        string temp = Path.Combine(data, "tmp");
        try
        {
            Directory.CreateDirectory(temp);
        }
        catch (Exception e)
        {
            Fail(Tr("無法建立資料夾 " + temp + "：" + e.Message + "\n請把程式放在可以寫入的位置（例如桌面或 D:\\），不要放在 Program Files。",
                    "Cannot create the folder " + temp + ": " + e.Message + "\nPut the program where it can write (for example the desktop or D:\\), not in Program Files."));
            return 1;
        }

        var start = new ProcessStartInfo(python, ("-I -X utf8 -m funscript_gen.cli " + command + " " + Arguments()).Trim());
        start.UseShellExecute = false;
        start.EnvironmentVariables["FUNSCRIPT_GEN_HOME"] = data;
        start.EnvironmentVariables["FUNSCRIPT_GEN_LANG_DIR"] = Path.Combine(root, "lang");
        start.EnvironmentVariables["TEMP"] = temp;
        start.EnvironmentVariables["TMP"] = temp;
#if GUI
        Process.Start(start);
        return 0;
#else
        // Ctrl+C reaches Python too (same console): wait for it to stop instead of leaving it running.
        Console.CancelKeyPress += (sender, e) => { e.Cancel = true; };
        using (Process child = Process.Start(start))
        {
            child.WaitForExit();
            return child.ExitCode;
        }
#endif
    }
}
