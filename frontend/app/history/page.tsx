'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { History, MessageSquare, FileText, BarChart3, LogOut, Clock } from 'lucide-react';
import Link from 'next/link';
import { format } from 'date-fns';
import { useAuth } from '@/hooks/useAuth';
import { api, QueryHistoryItem } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { Button } from '@/components/ui/Button';
import { formatLatency } from '@/lib/utils';

export default function HistoryPage() {
  const { isAuthenticated, isLoading: authLoading, logout, user } = useAuth();
  const router = useRouter();

  const { data: history = [], isLoading } = useQuery({
    queryKey: queryKeys.queries.history(50),
    queryFn: () => api.getQueryHistory(50),
    enabled: isAuthenticated,
  });

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
            <Button variant="ghost" className="w-full justify-start">
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
          
          <Link href="/history">
            <Button variant="secondary" className="w-full justify-start">
              <History className="w-4 h-4 mr-2" />
              History
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

      {/* Main Content */}
      <div className="flex-1 overflow-auto">
        <div className="max-w-4xl mx-auto p-8 space-y-8">
          {/* Header */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <h1 className="text-3xl font-bold mb-2">Query History</h1>
            <p className="text-muted-foreground">
              View your past conversations and responses
            </p>
          </motion.div>

          {/* History List */}
          {isLoading ? (
            <div className="p-12 text-center">
              <div className="inline-block w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              <p className="mt-2 text-sm text-muted-foreground">Loading history...</p>
            </div>
          ) : history.length === 0 ? (
            <div className="p-12 text-center border rounded-lg">
              <History className="w-12 h-12 mx-auto text-muted-foreground mb-3" />
              <p className="text-sm text-muted-foreground">No query history yet</p>
            </div>
          ) : (
            <div className="space-y-4">
              {(history as QueryHistoryItem[]).map((item, index) => (
                <motion.div
                  key={item.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: index * 0.05 }}
                  className="p-6 rounded-lg border bg-card hover:shadow-md transition-shadow"
                >
                  <div className="flex items-start justify-between mb-3">
                    <p className="font-medium">{item.query}</p>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Clock className="w-3 h-3" />
                      {formatLatency(item.latency_ms)}
                    </div>
                  </div>
                  
                  <p className="text-sm text-muted-foreground mb-3">
                    {item.response}
                  </p>
                  
                  <div className="flex items-center gap-4 text-xs text-muted-foreground pt-3 border-t">
                    <span>
                      {format(new Date(item.created_at), 'MMM d, yyyy h:mm a')}
                    </span>
                    <span>•</span>
                    <span>{item.sources_count} sources</span>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}