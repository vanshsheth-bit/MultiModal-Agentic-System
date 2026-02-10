'use client';

import { motion } from 'framer-motion';
import { File, FileText, FileAudio, FileType } from 'lucide-react';
import { format } from 'date-fns';
import { useState } from 'react';
import { Document } from '@/lib/api';
import { api, QueryResponse } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { MessageWithSources } from '@/components/chat/MessageWithSources';

interface DocumentTableProps {
  documents: Document[];
}

function getFileIcon(contentType?: string) {
  if (!contentType) return FileType;
  
  if (contentType.includes('pdf')) return File;
  if (contentType.includes('audio')) return FileAudio;
  if (contentType.includes('text')) return FileText;
  
  return FileType;
}

export function DocumentTable({ documents }: DocumentTableProps) {
  const [isSummarizing, setIsSummarizing] = useState<number | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summaryTitle, setSummaryTitle] = useState('');
  const [summary, setSummary] = useState<QueryResponse | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [activeDocId, setActiveDocId] = useState<number | null>(null);
  const [docQuestion, setDocQuestion] = useState('');
  const [docAnswer, setDocAnswer] = useState<QueryResponse | null>(null);
  const [isAnswering, setIsAnswering] = useState(false);

  const summarizeDoc = async (doc: Document) => {
    setIsSummarizing(doc.id);
    setSummaryError(null);
    setSummaryTitle(doc.filename);
    setSummaryOpen(true);
    setSummary(null);
    setActiveDocId(doc.id);
    setDocQuestion('');
    setDocAnswer(null);
    try {
      const res = await api.summarizeDocument(doc.id);
      setSummary(res);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to summarize document';
      setSummaryError(msg);
    } finally {
      setIsSummarizing(null);
    }
  };

  const ocrLabel = (doc: Document) => {
    const s = String(doc.ocr_status || '').toLowerCase();
    if (!s || s === 'not_needed') return '';
    if (s === 'queued') return 'OCR queued';
    if (s === 'running') {
      const done = typeof doc.ocr_pages_done === 'number' ? doc.ocr_pages_done : null;
      const total = typeof doc.ocr_pages_total === 'number' ? doc.ocr_pages_total : null;
      if (done !== null && total !== null && total > 0) return `OCR ${done}/${total}`;
      return 'OCR running';
    }
    if (s === 'done') return 'OCR done';
    if (s === 'failed') return 'OCR failed';
    return `OCR: ${s}`;
  };

  const askDoc = async () => {
    if (!activeDocId || !docQuestion.trim()) return;
    setIsAnswering(true);
    setSummaryError(null);
    try {
      const res = await api.answerFromDocument(activeDocId, docQuestion.trim());
      setDocAnswer(res);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || 'Failed to answer from document';
      setSummaryError(msg);
    } finally {
      setIsAnswering(false);
    }
  };

  if (documents.length === 0) {
    return (
      <div className="p-8 text-center border rounded-lg">
        <File className="w-12 h-12 mx-auto text-muted-foreground mb-3" />
        <p className="text-sm text-muted-foreground">No documents uploaded yet</p>
      </div>
    );
  }

  return (
    <div className="border rounded-lg overflow-hidden">
      {summaryOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl rounded-lg bg-background border shadow-lg">
            <div className="flex items-center justify-between px-4 py-3 border-b">
              <div className="min-w-0">
                <div className="text-sm font-semibold truncate">Summary</div>
                <div className="text-xs text-muted-foreground truncate">{summaryTitle}</div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setSummaryOpen(false)}>
                Close
              </Button>
            </div>
            <div className="p-4 space-y-3">
              {summaryError && <div className="text-sm text-red-600">{summaryError}</div>}
              {!summary && !summaryError && (
                <div className="text-sm text-muted-foreground">Summarizing…</div>
              )}
              {summary && (
                <MessageWithSources
                  content={summary.answer}
                  sources={summary.sources}
                  latency={summary.latency_ms}
                />
              )}

              <div className="pt-3 border-t space-y-2">
                <div className="text-xs font-medium text-muted-foreground">Ask this document</div>
                <div className="flex gap-2">
                  <input
                    value={docQuestion}
                    onChange={(e) => setDocQuestion(e.target.value)}
                    placeholder="Ask a question about this document…"
                    className="h-9 flex-1 rounded-md border bg-background px-3 text-sm"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={isAnswering || !docQuestion.trim()}
                    onClick={askDoc}
                  >
                    {isAnswering ? 'Asking…' : 'Ask'}
                  </Button>
                </div>

                {docAnswer && (
                  <div className="pt-2">
                    <MessageWithSources
                      content={docAnswer.answer}
                      sources={docAnswer.sources}
                      latency={docAnswer.latency_ms}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
      <table className="w-full">
        <thead className="bg-muted/50">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Name
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Type
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Uploaded
            </th>
            <th className="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {documents.map((doc, index) => {
            const Icon = getFileIcon(doc.content_type);
            const label = ocrLabel(doc);
            const ocrBusy = doc.ocr_status === 'queued' || doc.ocr_status === 'running';
            const ocrFailed = doc.ocr_status === 'failed';
            
            return (
              <motion.tr
                key={doc.id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: index * 0.05 }}
                className="hover:bg-muted/50 transition-colors"
              >
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <Icon className="w-4 h-4 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">{doc.filename}</div>
                      {label && (
                        <div className="text-xs text-muted-foreground truncate">
                          {label}{ocrFailed && doc.ocr_error ? `: ${doc.ocr_error}` : ''}
                        </div>
                      )}
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="text-sm text-muted-foreground">
                    {doc.content_type || 'Unknown'}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className="text-sm text-muted-foreground">
                    {doc.created_at
                      ? format(new Date(doc.created_at), 'MMM d, yyyy')
                      : 'Unknown'}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={isSummarizing === doc.id || ocrBusy}
                    onClick={() => summarizeDoc(doc)}
                  >
                    {isSummarizing === doc.id ? 'Summarizing…' : 'Summarize'}
                  </Button>
                </td>
              </motion.tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}