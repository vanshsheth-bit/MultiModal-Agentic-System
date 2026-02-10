
'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { MessageSquare, FileText, BarChart3, LogOut, Menu } from 'lucide-react';
import Link from 'next/link';
import { useAuth } from '@/hooks/useAuth';
import { useChat } from '@/hooks/useChat';
import { Button } from '@/components/ui/Button';
import { ChatInput } from '@/components/chat/ChatInput';
import { MessageList } from '@/components/chat/MessageList';
import { VoiceRecorder } from '@/components/chat/VoiceRecorder';
import { cn } from '@/lib/utils';

export default function ChatPage() {
  const { isAuthenticated, isLoading: authLoading, logout, user } = useAuth();
  const { messages, isLoading, error, streamingContent, sendMessage, sendAudioMessage } = useChat();
  const router = useRouter();

  const [sourceFilter, setSourceFilter] = useState('');
  const [contentTypeFilter, setContentTypeFilter] = useState('');

  const activeFilters = useMemo(() => {
    const sf = sourceFilter.trim();
    const ctf = contentTypeFilter.trim();
    return {
      sourceFilter: sf.length ? sf : undefined,
      contentTypeFilter: ctf.length ? ctf : undefined,
    };
  }, [sourceFilter, contentTypeFilter]);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.push('/');
    }
  }, [isAuthenticated, authLoading, router]);

  if (authLoading || !isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-pulse">Loading...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex bg-background">
      {/* Sidebar */}
      <motion.aside
        initial={{ x: -300 }}
        animate={{ x: 0 }}
        transition={{ duration: 0.3 }}
        className="w-64 border-r bg-card/50 backdrop-blur flex flex-col"
      >
        <div className="p-4 border-b">
          <h1 className="text-xl font-bold flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <MessageSquare className="w-5 h-5 text-primary-foreground" />
            </div>
            DocuMind
          </h1>
        </div>
        
        <nav className="flex-1 p-4 space-y-2">
          <Link href="/chat">
            <Button variant="secondary" className="w-full justify-start">
              <MessageSquare className="w-4 h-4 mr-2" />
              Chat
            </Button>
          </Link>
          
          <Link href="/dashboard">
            <Button variant="ghost" className="w-full justify-start">
              <FileText className="w-4 h-4 mr-2" />
              Documents
            </Button>
          </Link>
          
          <Link href="/admin">
            <Button variant="ghost" className="w-full justify-start">
              <BarChart3 className="w-4 h-4 mr-2" />
              Analytics
            </Button>
          </Link>
        </nav>
        
        <div className="p-4 border-t space-y-2">
          <div className="px-3 py-2 rounded-md bg-muted/50">
            <p className="text-xs font-medium truncate">{user?.username}</p>
            <p className="text-xs text-muted-foreground capitalize">{user?.tier} Plan</p>
          </div>
          
          <Button 
            variant="outline" 
            className="w-full justify-start text-red-600 hover:text-red-600 hover:bg-red-50"
            onClick={logout}
          >
            <LogOut className="w-4 h-4 mr-2" />
            Sign Out
          </Button>
        </div>
      </motion.aside>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <header className="h-16 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 flex items-center justify-between px-6">
          <div>
            <h2 className="text-lg font-semibold">AI Assistant</h2>
            <p className="text-xs text-muted-foreground">
              Ask anything about your documents
            </p>
          </div>

          <div className="flex items-center gap-2">
            <input
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              placeholder="Filter by filename…"
              className="h-9 w-56 rounded-md border bg-background px-3 text-sm"
              disabled={isLoading}
            />
            <select
              value={contentTypeFilter}
              onChange={(e) => setContentTypeFilter(e.target.value)}
              className="h-9 rounded-md border bg-background px-2 text-sm"
              disabled={isLoading}
            >
              <option value="">All types</option>
              <option value="pdf">pdf</option>
              <option value="audio">audio</option>
              <option value="text">text</option>
            </select>
          </div>
          
          <VoiceRecorder 
            onRecordingComplete={sendAudioMessage}
            disabled={isLoading}
          />
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {messages.length === 0 && !streamingContent ? (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex-1 flex items-center justify-center p-8"
            >
              <div className="text-center space-y-6 max-w-2xl">
                <div className="inline-flex p-4 rounded-full bg-primary/10">
                  <MessageSquare className="w-12 h-12 text-primary" />
                </div>
                
                <div className="space-y-2">
                  <h3 className="text-2xl font-bold">Start a Conversation</h3>
                  <p className="text-muted-foreground">
                    Ask questions about your documents and get instant, accurate answers
                    powered by advanced AI.
                  </p>
                </div>
                
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-4">
                  {[
                    'What are the main topics in my documents?',
                    'Summarize the key findings',
                    'What does the policy say about X?',
                    'Compare document A with document B',
                  ].map((suggestion, i) => (
                    <button
                      key={i}
                      onClick={() => sendMessage(suggestion, true, activeFilters)}
                      className="p-4 text-left rounded-lg border hover:bg-accent transition-colors text-sm"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            </motion.div>
          ) : (
            <MessageList
              messages={messages}
              streamingContent={streamingContent}
              isLoading={isLoading}
            />
          )}

          {error && (
            <div className="mx-4 mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-sm">
              {error}
            </div>
          )}

          <ChatInput
            onSendMessage={(msg) => sendMessage(msg, true, activeFilters)}
            isLoading={isLoading}
            placeholder="Ask anything about your documents..."
          />
        </div>
      </div>
    </div>
  );
}