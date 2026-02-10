'use client';

import { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp, File, Clock, Copy } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import { formatLatency } from '@/lib/utils';
import { Button } from '@/components/ui/Button';

interface Source {
  filename: string;
  content_type: string;
  relevance: number;
  retrieval_relevance?: number;
  text: string;
  page_number?: number | null;
  timestamp_start?: number | null;
  timestamp_end?: number | null;
  language?: string | null;
  confidence?: number | null;
}

interface MessageWithSourcesProps {
  content: string;
  sources: Source[];
  latency?: number;
  toolConfidence?: any;
}

type GroupedSource = {
  filename: string;
  content_type?: string;
  best_relevance: number;
  snippets: Source[];
};

export function MessageWithSources({ content, sources, latency, toolConfidence }: MessageWithSourcesProps) {
  const [showSources, setShowSources] = useState(false);
  const [showToolConfidence, setShowToolConfidence] = useState(false);
  const [expandedDocs, setExpandedDocs] = useState<Record<string, boolean>>({});

  const groupedSources = useMemo((): GroupedSource[] => {
    const map = new Map<string, Source[]>();
    for (const s of sources || []) {
      const key = s.filename;
      const arr = map.get(key) || [];
      arr.push(s);
      map.set(key, arr);
    }

    const groups: GroupedSource[] = [];
    for (const [filename, snippets] of map.entries()) {
      const sorted = [...snippets].sort((a, b) => b.relevance - a.relevance);
      groups.push({
        filename,
        content_type: sorted[0]?.content_type,
        best_relevance: sorted[0]?.relevance ?? 0,
        snippets: sorted,
      });
    }

    return groups.sort((a, b) => b.best_relevance - a.best_relevance);
  }, [sources]);

  const totalSnippetCount = sources?.length ?? 0;
  const docCount = groupedSources.length;

  return (
    <div className="space-y-3">
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
      
      {sources && sources.length > 0 && (
        <div className="mt-3 pt-3 border-t border-border/50">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowSources(!showSources)}
            className="w-full justify-between text-xs"
          >
            <span className="flex items-center gap-2">
              <File className="w-3 h-3" />
              {docCount} document{docCount !== 1 ? 's' : ''}
              <span className="text-muted-foreground">•</span>
              {totalSnippetCount} match{totalSnippetCount !== 1 ? 'es' : ''}
              {latency && (
                <>
                  <span className="text-muted-foreground">•</span>
                  <Clock className="w-3 h-3" />
                  {formatLatency(latency)}
                </>
              )}
            </span>
            {showSources ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </Button>

          {toolConfidence && (
            <div className="mt-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowToolConfidence(!showToolConfidence)}
                className="w-full justify-between text-xs"
              >
                <span className="text-muted-foreground">Tool confidence</span>
                {showToolConfidence ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </Button>

              <AnimatePresence>
                {showToolConfidence && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="mt-2 rounded-md bg-background/50 border border-border/30 p-3 text-[11px] text-muted-foreground space-y-1">
                      {['transcription', 'retrieval', 'llm'].map((k) => {
                        const v = toolConfidence?.[k];
                        if (!v) return null;
                        const conf = typeof v.confidence === 'number' ? Math.round(v.confidence * 100) : null;
                        return (
                          <div key={k} className="flex items-center justify-between">
                            <span className="capitalize">{k}</span>
                            <span>{conf !== null ? `${conf}%` : '—'}</span>
                          </div>
                        );
                      })}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
          
          <AnimatePresence>
            {showSources && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="mt-2 space-y-2">
                  {groupedSources.map((group) => {
                    const expanded = Boolean(expandedDocs[group.filename]);
                    const visibleSnippets = expanded ? group.snippets : group.snippets.slice(0, 2);
                    const remaining = Math.max(0, group.snippets.length - visibleSnippets.length);

                    return (
                      <div
                        key={group.filename}
                        className="p-3 rounded-md bg-background/50 border border-border/30"
                      >
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedDocs((prev) => ({
                              ...prev,
                              [group.filename]: !expanded,
                            }))
                          }
                          className="w-full text-left"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-medium truncate pr-3">{group.filename}</span>
                            <span className="text-xs text-muted-foreground flex-shrink-0">
                              {group.best_relevance.toFixed(0)}% relevant
                            </span>
                          </div>
                          <div className="mt-1 flex items-center justify-between">
                            <span className="text-[11px] text-muted-foreground">
                              {group.content_type || 'document'}
                              <span className="text-muted-foreground"> • </span>
                              {group.snippets.length} snippet{group.snippets.length !== 1 ? 's' : ''}
                            </span>
                            <span className="text-[11px] text-muted-foreground flex items-center gap-1">
                              {expanded ? 'Hide' : 'View'}
                              {expanded ? (
                                <ChevronUp className="w-3 h-3" />
                              ) : (
                                <ChevronDown className="w-3 h-3" />
                              )}
                            </span>
                          </div>
                        </button>

                        <div className="mt-2 space-y-2">
                          {visibleSnippets.map((snippet, idx) => (
                            <div key={idx} className="rounded-md bg-muted/40 p-2">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-[11px] text-muted-foreground">
                                  {snippet.relevance.toFixed(0)}% match
                                </span>
                                <div className="flex items-center gap-2">
                                  <span className="text-[11px] text-muted-foreground text-right">
                                    {snippet.content_type === 'pdf' &&
                                      typeof snippet.page_number === 'number' &&
                                      snippet.page_number > 0 && (
                                        <>p. {snippet.page_number}</>
                                      )}
                                    {snippet.content_type === 'audio' &&
                                      typeof snippet.timestamp_start === 'number' &&
                                      typeof snippet.timestamp_end === 'number' && (
                                        <>
                                          {snippet.timestamp_start.toFixed(1)}s–{snippet.timestamp_end.toFixed(1)}s
                                        </>
                                      )}
                                  </span>
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="h-6 px-2"
                                    onClick={async () => {
                                      try {
                                        await navigator.clipboard.writeText(String(snippet.text || ''));
                                      } catch {
                                        // ignore
                                      }
                                    }}
                                  >
                                    <Copy className="w-3 h-3" />
                                  </Button>
                                </div>
                              </div>
                              {(snippet.language || typeof snippet.confidence === 'number') && (
                                <div className="mb-1 flex items-center justify-between">
                                  <span className="text-[11px] text-muted-foreground">
                                    {snippet.language ? `lang: ${snippet.language}` : ''}
                                  </span>
                                  <span className="text-[11px] text-muted-foreground">
                                    {typeof snippet.confidence === 'number'
                                      ? `conf: ${Math.round(snippet.confidence * 100)}%`
                                      : ''}
                                  </span>
                                </div>
                              )}
                              <p className="text-xs text-muted-foreground line-clamp-3">
                                {snippet.text}
                              </p>
                            </div>
                          ))}

                          {!expanded && remaining > 0 && (
                            <div className="text-[11px] text-muted-foreground">
                              +{remaining} more snippet{remaining !== 1 ? 's' : ''}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}