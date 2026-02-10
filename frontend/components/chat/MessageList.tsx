'use client';

import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { User, Bot } from 'lucide-react';
import { MessageWithSources } from './MessageWithSources';
import { cn } from '@/lib/utils';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: any[];
  toolConfidence?: any;
  latency?: number;
  timestamp: Date;
}

interface MessageListProps {
  messages: Message[];
  streamingContent?: string;
  isLoading?: boolean;
}

export function MessageList({ messages, streamingContent, isLoading }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
      <AnimatePresence initial={false}>
        {messages.map((message, index) => (
          <motion.div
            key={message.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3, delay: index * 0.05 }}
            className={cn(
              'flex gap-3',
              message.role === 'user' ? 'justify-end' : 'justify-start'
            )}
          >
            {message.role === 'assistant' && (
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary flex items-center justify-center">
                <Bot className="w-5 h-5 text-primary-foreground" />
              </div>
            )}
            
            <div
              className={cn(
                'max-w-[80%] rounded-lg px-4 py-3',
                message.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted'
              )}
            >
              {message.role === 'assistant' && message.sources ? (
                <MessageWithSources
                  content={message.content}
                  sources={message.sources}
                  latency={message.latency}
                  toolConfidence={message.toolConfidence}
                />
              ) : (
                <p className="text-sm whitespace-pre-wrap">{message.content}</p>
              )}
            </div>
            
            {message.role === 'user' && (
              <div className="flex-shrink-0 w-8 h-8 rounded-full bg-secondary flex items-center justify-center">
                <User className="w-5 h-5" />
              </div>
            )}
          </motion.div>
        ))}
      </AnimatePresence>
      
      {streamingContent && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex gap-3"
        >
          <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary flex items-center justify-center">
            <Bot className="w-5 h-5 text-primary-foreground" />
          </div>
          <div className="max-w-[80%] rounded-lg px-4 py-3 bg-muted">
            <p className="text-sm whitespace-pre-wrap">{streamingContent}</p>
            <span className="inline-block w-1 h-4 ml-1 bg-foreground animate-pulse" />
          </div>
        </motion.div>
      )}
      
      {isLoading && !streamingContent && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex gap-3"
        >
          <div className="flex-shrink-0 w-8 h-8 rounded-full bg-primary flex items-center justify-center">
            <Bot className="w-5 h-5 text-primary-foreground" />
          </div>
          <div className="max-w-[80%] rounded-lg px-4 py-3 bg-muted">
            <div className="flex gap-1">
              <span className="w-2 h-2 rounded-full bg-foreground/40 animate-pulse" />
              <span className="w-2 h-2 rounded-full bg-foreground/40 animate-pulse [animation-delay:0.2s]" />
              <span className="w-2 h-2 rounded-full bg-foreground/40 animate-pulse [animation-delay:0.4s]" />
            </div>
          </div>
        </motion.div>
      )}
      
      <div ref={bottomRef} />
    </div>
  );
}