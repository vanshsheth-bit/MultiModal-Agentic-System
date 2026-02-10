import { useState, useCallback, useRef, useEffect } from 'react';
import { api, QueryResponse } from '@/lib/api';
import { ChatWebSocket } from '@/lib/websocket';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: QueryResponse['sources'];
  toolConfidence?: QueryResponse['tool_confidence'];
  latency?: number;
  timestamp: Date;
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingContent, setStreamingContent] = useState('');
  const [isStreamingConnected, setIsStreamingConnected] = useState(false);
  const wsRef = useRef<ChatWebSocket | null>(null);
  const streamBufferRef = useRef('');
  const receivedFinalRef = useRef(false);

  const addMessage = useCallback((message: Omit<Message, 'id' | 'timestamp'>) => {
    const newMessage: Message = {
      ...message,
      id: Math.random().toString(36).substr(2, 9),
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, newMessage]);
    return newMessage;
  }, []);

  const sendMessage = useCallback(
    async (
      query: string,
      useStreaming: boolean = true,
      filters?: { sourceFilter?: string; contentTypeFilter?: string }
    ) => {
    if (!query.trim()) return;

    setError(null);
    
    // Add user message
    addMessage({
      role: 'user',
      content: query,
    });

    const hasFilters = Boolean(filters?.sourceFilter || filters?.contentTypeFilter);
    const canStream =
      !hasFilters && useStreaming && isStreamingConnected && wsRef.current?.isConnected();

    if (canStream) {
      setIsLoading(true);
      streamBufferRef.current = '';
      receivedFinalRef.current = false;
      setStreamingContent('');

      try {
        wsRef.current!.sendMessage(query);
        return;
      } catch {
        // Fall back to HTTP below
      }
    }

    setIsLoading(true);
    try {
      const response = await api.queryText(query, {
        sourceFilter: filters?.sourceFilter,
        contentTypeFilter: filters?.contentTypeFilter,
      });
      addMessage({
        role: 'assistant',
        content: response.answer,
        sources: response.sources,
        toolConfidence: response.tool_confidence,
        latency: response.latency_ms,
      });
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || 'Failed to get response';
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
    },
    [addMessage, isStreamingConnected]
  );

  const sendAudioMessage = useCallback(async (audioFile: File) => {
    setError(null);
    setIsLoading(true);
    
    // Add user message placeholder
    addMessage({
      role: 'user',
      content: '[Audio message]',
    });

    try {
      const response = await api.queryAudio(audioFile);
      
      addMessage({
        role: 'assistant',
        content: response.answer,
        sources: response.sources,
        latency: response.latency_ms,
      });
    } catch (err: any) {
      const errorMessage = err.response?.data?.detail || 'Failed to process audio';
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, [addMessage]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setStreamingContent('');
    setError(null);
  }, []);

  // Initialize WebSocket
  useEffect(() => {
    const ws = new ChatWebSocket(
      (data) => {
        if (data.type === 'token') {
          streamBufferRef.current += String(data.content ?? '');
          setStreamingContent(streamBufferRef.current);
        } else if (data.type === 'final') {
          receivedFinalRef.current = true;
          addMessage({
            role: 'assistant',
            content: String(data.answer ?? streamBufferRef.current),
            sources: data.sources ?? [],
            toolConfidence: data.tool_confidence,
            latency: data.latency_ms,
          });
          streamBufferRef.current = '';
          setStreamingContent('');
          setIsLoading(false);
        } else if (data.type === 'done') {
          if (!receivedFinalRef.current) {
            addMessage({
              role: 'assistant',
              content: streamBufferRef.current,
            });
          }
          streamBufferRef.current = '';
          setStreamingContent('');
          setIsLoading(false);
        } else if (data.type === 'error') {
          setError(data.message);
          streamBufferRef.current = '';
          receivedFinalRef.current = false;
          setStreamingContent('');
          setIsLoading(false);
        }
      },
      (error) => {
        console.error('WebSocket error:', error);
      },
      () => {
        setIsStreamingConnected(true);
      },
      () => {
        setIsStreamingConnected(false);
      }
    );

    ws.connect();
    wsRef.current = ws;

    return () => {
      ws.disconnect();
    };
  }, [addMessage]);

  return {
    messages,
    isLoading,
    error,
    streamingContent,
    isStreamingConnected,
    sendMessage,
    sendAudioMessage,
    clearMessages,
  };
}