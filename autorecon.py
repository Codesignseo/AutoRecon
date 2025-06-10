import subprocess
import requests
import sys
import os
import json
import locale
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import threading
import http.server
import socketserver
import webbrowser
import time
import shutil

def run_cmd(cmd):
    exe = cmd.split()[0]
    if shutil.which(exe) is None:
        return f"[ERROR] Command not found: {exe}"
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=locale.getpreferredencoding(False)
        )
        return result.stdout
    except Exception as e:
        return f"Error running command: {cmd}\n{str(e)}"

def protocol_check(target):
    protocol = None
    try:
        response = requests.get(f"https://{target}", timeout=5)
        if response.status_code < 400:
            protocol = "https"
    except:
        try:
            response = requests.get(f"http://{target}", timeout=5)
            if response.status_code < 400:
                protocol = "http"
        except:
            protocol = None
    return protocol

def update_results_json(target, results):
    base_dir = f"scans/{target}"
    os.makedirs(base_dir, exist_ok=True)
    json_path = f"{base_dir}/results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

def scan_task(name, cmd, target, results):
    print(f"[*] Running {name}...")
    output = run_cmd(cmd)
    results[name] = output
    update_results_json(target, results)
    return (name, output)

def generate_html_report(target):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_content = f"""
    <html>
    <head>
        <title>Scan Report for {target}</title>
        <style>
            body {{ font-family: monospace; background: #1e1e1e; color: #c5c5c5; padding: 20px; }}
            h1 {{ border-bottom: 2px solid #444; padding-bottom: 10px; }}
            h2 {{ border-bottom: 1px solid #444; padding-bottom: 5px; margin-top: 20px; }}
            pre {{ background: #2d2d2d; padding: 10px; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; }}
        </style>
        <script>
        async function fetchResults() {{
            try {{
                const resp = await fetch('results.json?' + Date.now());
                const data = await resp.json();
                let html = '';
                for (const [name, output] of Object.entries(data)) {{
                    html += `<h2>${{name}}</h2><pre>${{output.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}}</pre>`;
                }}
                document.getElementById('results').innerHTML = html;
            }} catch (e) {{
                document.getElementById('results').innerHTML = '<i>Waiting for results...</i>';
            }}
        }}
        setInterval(fetchResults, 2000);
        window.onload = fetchResults;
        </script>
    </head>
    <body>
        <h1>Scan Report for {target}</h1>
        <p>Scan time: {now}</p>
        <div id="results"></div>
    </body>
    </html>
    """

    base_dir = f"scans/{target}"
    os.makedirs(base_dir, exist_ok=True)
    report_path = f"{base_dir}/report.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[+] Report generated at {report_path}")

def start_http_server(directory, port):
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=directory, **kwargs)
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"[+] Serving HTTP on port {port} (http://localhost:{port}/)")
        httpd.serve_forever()

def load_flags():
    try:
        with open("flags.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def main(target):
    protocol = protocol_check(target)
    base_dir = f"scans/{target}"
    os.makedirs(base_dir, exist_ok=True)
    port = 8765
    server_thread = threading.Thread(target=start_http_server, args=(base_dir, port), daemon=True)
    server_thread.start()
    time.sleep(1)

    flags = load_flags()
    url = f"{'https' if protocol == 'https' else 'http'}://{target}"

    # Only add commands that are present in flags.json
    commands = {}

    if "Nmap Scan" in flags:
        commands["Nmap Scan"] = f"nmap {flags['Nmap Scan']} {target}"
    if "HTTP Headers" in flags and protocol:
        commands["HTTP Headers"] = f"curl {flags['HTTP Headers']} {url}"
    if "WhatWeb" in flags and protocol:
        commands["WhatWeb"] = f"whatweb {flags['WhatWeb']} {url}"
    if "Whois Info" in flags:
        commands["Whois Info"] = f"whois {flags['Whois Info']} {target}".strip()
    if "Amass Enum" in flags:
        commands["Amass Enum"] = f"amass {flags['Amass Enum']} {target}"
    if "theHarvester" in flags:
        commands["theHarvester"] = f"theHarvester {flags['theHarvester']}".replace("{target}", target)
    if "DNSRecon" in flags:
        commands["DNSRecon"] = f"dnsrecon {flags['DNSRecon']} {target}"
    if "SSLScan" in flags:
        commands["SSLScan"] = f"sslscan {flags['SSLScan']} {target}".strip()
    if "Nikto Scan" in flags and protocol:
        commands["Nikto Scan"] = f"nikto {flags['Nikto Scan']} {url}"
    if "Gobuster Scan" in flags and protocol:
        commands["Gobuster Scan"] = f"gobuster {flags['Gobuster Scan']}".replace("{url}", url)
    if "Nuclei Scan" in flags and protocol:
        commands["Nuclei Scan"] = f"nuclei {flags['Nuclei Scan']}".replace("{url}", url)
    if "Subfinder" in flags:
        commands["Subfinder"] = f"subfinder {flags['Subfinder']} {target}"

    if not protocol:
        for key in ["Nikto Scan", "Gobuster Scan", "WhatWeb", "HTTP Headers", "Nuclei Scan"]:
            if key in commands:
                del commands[key]

    results = {name: "" for name in commands}
    update_results_json(target, results)
    generate_html_report(target, commands)

    report_url = f"http://localhost:{port}/report.html"
    print(f"[+] Opening report: {report_url}")
    webbrowser.open(report_url)

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = []
        for name, cmd in commands.items():
            futures.append(executor.submit(scan_task, name, cmd, target, results))
        for future in as_completed(futures):
            name, output = future.result()
            results[name] = output
            update_results_json(target, results)

    print(f"[*] Done! Check the folder scans/{target}/")
    print("[*] HTTP server is still running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Exiting by user request.")

def generate_html_report(target, commands):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commands_json = json.dumps(list(commands.keys()))
    html_content = f"""
    <html>
    <head>
        <title>Scan Report for {target}</title>
        <style>
            body {{ font-family: monospace; background: #1e1e1e; color: #c5c5c5; padding: 20px; }}
            h1 {{ border-bottom: 2px solid #444; padding-bottom: 10px; }}
            h2 {{ border-bottom: 1px solid #444; padding-bottom: 5px; margin-top: 20px; }}
            .pre-wrap {{ background: #2d2d2d; padding: 10px; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; }}
            .toggle-btn {{ cursor: pointer; color: #7ecfff; font-size: 1.2em; margin-left: 10px; }}
            .scrollable-output {{ max-height: 500px; overflow-y: auto; }}
        </style>
        <script>
        const commands = {commands_json};
        function escapeHtml(text) {{
            return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        }}
        function renderOutput(name, output) {{
            if (!output) {{
                return `<h2>${{name}}</h2><pre class="pre-wrap"><i>Waiting...</i></pre>`;
            }}
            const lines = output.split(/\\r?\\n/);
            if (lines.length <= 30) {{
                return `<h2>${{name}}</h2><pre class="pre-wrap">${{escapeHtml(output)}}</pre>`;
            }}
            const first = lines.slice(0, 50).join('\\n');
            const id = 'out_' + btoa(name).replace(/[^a-zA-Z0-9]/g, '');
            return `<h2>${{name}}</h2>
                <pre class="pre-wrap" id="${{id}}_short">${{escapeHtml(first)}}\\n<span class="toggle-btn" onclick="showFull('${{id}}')">&#x25BC; Show more</span></pre>
                <pre class="pre-wrap scrollable-output" id="${{id}}_full" style="display:none;">${{escapeHtml(output)}}\\n<span class="toggle-btn" onclick="showShort('${{id}}')">&#x25B2; Show less</span></pre>`;
        }}
        function showFull(id) {{
            document.getElementById(id + '_short').style.display = 'none';
            document.getElementById(id + '_full').style.display = '';
            window.expandedBlocks = window.expandedBlocks || {{}};
            window.expandedBlocks[id] = true;
        }}
        function showShort(id) {{
            document.getElementById(id + '_short').style.display = '';
            document.getElementById(id + '_full').style.display = 'none';
            window.expandedBlocks = window.expandedBlocks || {{}};
            window.expandedBlocks[id] = false;
        }}
        async function fetchResults() {{
            window.expandedBlocks = window.expandedBlocks || {{}};
            let expanded = Object.assign({{}}, window.expandedBlocks);
            try {{
                const resp = await fetch('results.json?' + Date.now());
                const data = await resp.json();
                let html = '';
                for (const name of commands) {{
                    html += renderOutput(name, data[name]);
                }}
                document.getElementById('results').innerHTML = html;
                // Restore expanded state
                for (const name of commands) {{
                    const id = 'out_' + btoa(name).replace(/[^a-zA-Z0-9]/g, '');
                    if (expanded[id]) {{
                        showFull(id);
                    }}
                }}
            }} catch (e) {{
                document.getElementById('results').innerHTML = '<i>Waiting for results...</i>';
            }}
        }}
        setInterval(fetchResults, 2000);
        window.onload = fetchResults;
        </script>
    </head>
    <body>
        <h1>Scan Report for {target}</h1>
        <p>Scan time: {now}</p>
        <div id="results"></div>
    </body>
    </html>
    """

    base_dir = f"scans/{target}"
    os.makedirs(base_dir, exist_ok=True)
    report_path = f"{base_dir}/report.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[+] Report generated at {report_path}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python autorecon.py <target_ip_or_domain>")
        sys.exit(1)
    main(sys.argv[1])
