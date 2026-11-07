"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, BookOpen, Bot, Database, Send, ShieldCheck, Sparkles, User } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import type { AssistantAnswer, Dataset } from "@/lib/types";
import { Badge, Button, EmptyState, InlineError, Spinner } from "@/components/ui";
import { useToast } from "@/components/ToastProvider";

const SUGGESTIONS = [
  "What is the refund approval threshold for a support lead?",
  "Which regions generated the most completed revenue?",
  "What customer data is classified as restricted?",
  "Summarise the return policy for EU customers.",
];

interface Message {
  role: "user" | "assistant";
  content: string;
  answer?: AssistantAnswer;
}

export default function AssistantPage() {
  const toast = useToast();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [question, setQuestion] = useState("");
  const [datasetFilter, setDatasetFilter] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Dataset[]>("/datasets")
      .then((rows) => {
        setDatasets(rows);
        const param = new URLSearchParams(window.location.search).get("dataset");
        if (param) setDatasetFilter(param);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  async function ask(value?: string) {
    const prompt = (value ?? question).trim();
    if (!prompt || asking) return;
    setQuestion("");
    setMessages((current) => [...current, { role: "user", content: prompt }]);
    setAsking(true);
    try {
      const answer = await api.post<AssistantAnswer>("/assist/ask", {
        question: prompt,
        dataset_ids: datasetFilter ? [datasetFilter] : [],
        top_k: 6,
      });
      setMessages((current) => [...current, { role: "assistant", content: answer.answer, answer }]);
    } catch (err) {
      const message = errorMessage(err);
      setError(message);
      toast.push(message, "error");
    } finally {
      setAsking(false);
    }
  }

  if (loading) return <Spinner label="Loading assistant" />;

  return (
    <div className="page-stack assistant-page">
      <div className="assistant-header">
        <div>
          <div className="eyebrow">GenAI enablement</div>
          <h1>Ask Meridian</h1>
          <p>Retrieval is filtered by tenant and dataset access before generation. Every answer is grounded in cited source passages.</p>
        </div>
        <div className="assistant-scope">
          <label>Scope</label>
          <select value={datasetFilter} onChange={(event) => setDatasetFilter(event.target.value)}>
            <option value="">All datasets I can access</option>
            {datasets.filter((dataset) => dataset.can_read !== false).map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}
          </select>
          <Badge tone="success"><ShieldCheck size={12} /> ACL filtered</Badge>
        </div>
      </div>

      {error && <InlineError message={error} />}

      <div className="chat-shell">
        <div className="chat-thread">
          {messages.length === 0 && (
            <div className="chat-welcome">
              <div className="chat-orb"><Sparkles size={26} /></div>
              <h2>Governed answers, not guesses.</h2>
              <p>Ask about policies, customers or revenue. Meridian retrieves only documents and datasets your grants allow, then returns citations.</p>
              <div className="suggestion-grid">
                {SUGGESTIONS.map((suggestion) => <button key={suggestion} onClick={() => void ask(suggestion)}>{suggestion}</button>)}
              </div>
              <div className="assistant-grounding">
                <span><BookOpen size={14} /> Document chunks</span>
                <span><Database size={14} /> Catalog context</span>
                <span><ShieldCheck size={14} /> Access grants</span>
              </div>
            </div>
          )}
          {messages.map((message, index) => (
            <div key={index} className={`chat-message ${message.role}`}>
              <div className="chat-avatar">{message.role === "user" ? <User size={16} /> : <Bot size={16} />}</div>
              <div className="chat-bubble">
                {message.role === "assistant" ? <RichText text={message.content} /> : message.content}
                {message.answer && (
                  <div className="chat-answer-meta">
                    <Badge tone={message.answer.mode === "llm" ? "violet" : "neutral"}>{message.answer.mode}</Badge>
                    <span>{message.answer.model}</span>
                    <span>{message.answer.citations.length} citations</span>
                    <code>{message.answer.request_id}</code>
                  </div>
                )}
                {message.answer && message.answer.citations.length > 0 && (
                  <div className="citation-list">
                    {message.answer.citations.map((citation) => (
                      <Link href={`/catalog/${citation.dataset_id}`} key={citation.index} className="citation-card">
                        <span className="citation-index">[{citation.index}]</span>
                        <span><strong>{citation.title}</strong><small>page {citation.page || "—"} · {citation.source_uri.split("/").pop()}</small><em>{citation.snippet}</em></span>
                        <ArrowUpRight size={13} />
                      </Link>
                    ))}
                  </div>
                )}
                {message.answer && message.answer.catalog.length > 0 && (
                  <div className="related-assets">
                    <span>Related catalog assets:</span>
                    {message.answer.catalog.map((item) => <Link key={item.id} href={`/catalog/${item.id}`}>{item.name}</Link>)}
                  </div>
                )}
              </div>
            </div>
          ))}
          {asking && (
            <div className="chat-message assistant">
              <div className="chat-avatar"><Bot size={16} /></div>
              <div className="chat-bubble typing"><span /><span /><span /></div>
            </div>
          )}
        </div>

        <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); void ask(); }}>
          <textarea rows={2} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask a question about governed data…" onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void ask(); } }} />
          <Button variant="dark" type="submit" disabled={asking || !question.trim()}><Send size={15} /> Ask</Button>
        </form>
      </div>

      {messages.length === 0 && (
        <div className="assistant-guarantees">
          <div><ShieldCheck size={17} /><strong>Access before retrieval</strong><span>Restricted datasets are excluded unless an active grant exists.</span></div>
          <div><BookOpen size={17} /><strong>Citations or refusal</strong><span>Answers include source passages; insufficient context is stated explicitly.</span></div>
          <div><Sparkles size={17} /><strong>Model optional</strong><span>Works extractively by default; configure an LLM gateway for synthesis.</span></div>
        </div>
      )}
    </div>
  );
}

function RichText({ text }: { text: string }) {
  return (
    <>
      {text.split("\n").map((line, index) => {
        if (!line.trim()) return <br key={index} />;
        if (line.startsWith("**") && line.endsWith("**")) return <strong key={index}>{line.slice(2, -2)}</strong>;
        if (line.startsWith("- ")) return <div className="bullet" key={index}>• {line.slice(2)}</div>;
        return <p key={index}>{line}</p>;
      })}
    </>
  );
}
