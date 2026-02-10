'use client';

import { useState, useRef, KeyboardEvent } from 'react';
import { Send, Mic } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Textarea } from '@/components/ui/Textarea';
import { cn } from '@/lib/utils';

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  onSendAudio?: (file: File) => void;
  isLoading?: boolean;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({
  onSendMessage,
  onSendAudio,
  isLoading = false,
  disabled = false,
  placeholder = 'Ask anything...',
}: ChatInputProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = () => {
    if (!input.trim() || isLoading || disabled) return;
    
    onSendMessage(input);
    setInput('');
    
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    
    // Auto-resize textarea
    e.target.style.height = 'auto';
    e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
  };

  return (
    <div className="relative flex items-end gap-2 p-4 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <Textarea
        ref={textareaRef}
        value={input}
        onChange={handleTextareaChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled || isLoading}
        className={cn(
          'resize-none pr-12 min-h-[52px] max-h-[200px]',
          'focus:ring-1'
        )}
        rows={1}
      />
      
      <div className="absolute right-6 bottom-7 flex items-center gap-1">
        {onSendAudio && (
          <Button
            type="button"
            size="icon"
            variant="ghost"
            disabled={disabled || isLoading}
            className="h-8 w-8"
          >
            <Mic className="h-4 w-4" />
          </Button>
        )}
        
        <Button
          type="button"
          size="icon"
          onClick={handleSubmit}
          disabled={!input.trim() || disabled || isLoading}
          className="h-8 w-8"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}