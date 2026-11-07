"use client";

import { useEffect, useRef, useState } from "react";
import { Circle, CornerDownLeft, PlugZap, Shield, TerminalSquare, Trash2, Wifi, WifiOff } from "lucide-react";
import { getToken, terminalUrl } from "@/lib/api";
import { Badge, Button, PageHeader } from "@/components/ui";

const QUICK = ["help", "whoami", "sources", "datasets", "runs", "ask What is the refund policy?"];

export default function TerminalPage() {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [input, setInput] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const socketRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function append(text: string) {
    setLines((current) => [...current, ...text.replace(/\x1b\[[0-9;]*m/g, "").split("\n")]);
  }

  function connect() {
    const token = getToken();
    if (!token) {
      append("No session token. Sign in again.");
      return;
    }
    setConnecting(true);
    const socket = new WebSocket(terminalUrl(token));
    socketRef.current = socket;
    socket.onopen = () => {
      setConnected(true);
      setConnecting(false);
      append("Connected to Meridian remote terminal.");
      inputRef.current?.focus();
    };
    socket.onmessage = (event) => append(String(event.data));
    socket.onerror = () => {
      append("WebSocket error. Is the API running and reachable?");
      setConnecting(false);
    };
    socket.onclose = (event) => {
      setConnected(false);
      setConnecting(false);
      if (event.code !== 1000) append(`Session closed (${event.code}).`);
    };
  }

  useEffect(() => {
    connect();
    return () => socketRef.current?.close();
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [lines]);

  function send(command?: string) {
    const value = (command ?? input).trim();
    if (!value) return;
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      append("Not connected. Reconnect first.");
      return;
    }
    append(`meridian@acme:~$ ${value}`);
    socketRef.current.send(value);
    setHistory((current) => [value, ...current].slice(0, 50));
    setHistoryIndex(-1);
    setInput("");
    if (value === "clear") setLines([]);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      send();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const next = Math.min(historyIndex + 1, history.length - 1);
      if (next >= 0) { setHistoryIndex(next); setInput(history[next]); }
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = historyIndex - 1;
      setHistoryIndex(next);
      setInput(next >= 0 ? history[next] : "");
    } else if (event.key === "l" && event.ctrlKey) {
      event.preventDefault();
      setLines([]);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Operate"
        title="Remote terminal"
        description="A restricted application shell over WebSocket. It is tenant-scoped, audited and intentionally has no host shell."
        actions={
          <div className="terminal-status">
            <Badge tone={connected ? "success" : "danger"} dot>{connected ? "connected" : "disconnected"}</Badge>
            <Button variant="secondary" onClick={() => { setLines([]); connect(); }}><PlugZap size={15} /> Reconnect</Button>
          </div>
        }
      />

      <div className="terminal-layout">
        <section className="terminal-window">
          <div className="terminal-bar">
            <div className="terminal-dots"><span /><span /><span /></div>
            <div className="terminal-title"><TerminalSquare size={14} /> meridian@acme — application shell</div>
            <div className="terminal-bar-right">{connected ? <Wifi size={14} /> : <WifiOff size={14} />} ws</div>
          </div>
          <div className="terminal-body" ref={scrollRef} onClick={() => inputRef.current?.focus()}>
            <div className="terminal-masthead">
              <pre>{`  __  __ ___ ___ ___ ___   _   _ _
 |  \\/  | __| _ \\_ _|   \\ /_\\ | \\ | |
 | |\\/| | _||   /| || |) / _ \\|  \\| |
 |_|  |_|___|_|_\\___|___/_/ \\_\\_|\\__|`}</pre>
              <span>governed data platform · remote shell v0.1</span>
            </div>
            {lines.map((line, index) => (
              <div key={index} className={`term-line ${line.startsWith("meridian@acme") ? "term-command" : ""}`}>{line || "\u00a0"}</div>
            ))}
            {connecting && <div className="term-line muted">opening secure channel…</div>}
            <form className="term-prompt" onSubmit={(event) => { event.preventDefault(); send(); }}>
              <span className="prompt-user">meridian@acme</span><span className="prompt-path">:~$</span>
              <input ref={inputRef} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={onKeyDown} autoComplete="off" spellCheck={false} aria-label="Terminal command" />
              <CornerDownLeft size={13} />
            </form>
          </div>
        </section>

        <aside className="terminal-aside">
          <div className="panel">
            <div className="panel-head"><div><h2>Quick commands</h2><p>Read-only by default.</p></div></div>
            <div className="quick-commands">
              {QUICK.map((command) => <button key={command} onClick={() => send(command)}>{command}</button>)}
            </div>
          </div>
          <div className="panel terminal-guardrails">
            <div className="panel-head"><div><h2>Guardrails</h2><p>Why this is not a host shell.</p></div><Shield size={17} className="panel-icon" /></div>
            <ul className="clean-list">
              <li>Commands are implemented by the API, not <code>/bin/sh</code>.</li>
              <li>Every command is scoped to your tenant and role.</li>
              <li>Run starts require <code>runs:write</code> and are audited.</li>
              <li>No filesystem, package manager or network access.</li>
              <li>Session closes automatically when the JWT expires.</li>
            </ul>
          </div>
          <div className="terminal-foot">
            <span><Circle size={8} fill="currentColor" /> request IDs are returned after every command</span>
            <Button variant="ghost" size="sm" onClick={() => { setLines([]); inputRef.current?.focus(); }}><Trash2 size={14} /> Clear</Button>
          </div>
        </aside>
      </div>
    </div>
  );
}
