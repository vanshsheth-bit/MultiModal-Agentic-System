'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { motion } from 'framer-motion';
import { 
  FileText, 
  MessageSquare, 
  Users, 
  Activity,
  BarChart3,
  LogOut,
  TrendingUp,
  Clock
} from 'lucide-react';
import Link from 'next/link';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { useAuth } from '@/hooks/useAuth';
import { api } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { Button } from '@/components/ui/Button';
import { StatsCard } from '@/components/dashboard/StatsCard';
import { formatLatency } from '@/lib/utils';

export default function AdminPage() {
  const { isAuthenticated, isLoading: authLoading, logout, user } = useAuth();
  const router = useRouter();

  const { data: metrics, isLoading: metricsLoading } = useQuery({
    queryKey: queryKeys.admin.metrics(),
    queryFn: () => api.getMetrics(),
    enabled: isAuthenticated,
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  const { data: systemStatus } = useQuery({
    queryKey: queryKeys.admin.systemStatus(),
    queryFn: () => api.getSystemStatus(),
    enabled: isAuthenticated,
    refetchInterval: 30000, // Refresh every 30 seconds
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
          
          <Link href="/admin">
            <Button variant="secondary" className="w-full justify-start">
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
        <div className="max-w-7xl mx-auto p-8 space-y-8">
          {/* Header */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="flex items-center justify-between"
          >
            <div>
              <h1 className="text-3xl font-bold mb-2">Analytics Dashboard</h1>
              <p className="text-muted-foreground">
                Monitor your AI assistant's performance and usage
              </p>
            </div>
            
            {systemStatus && (
              <div className="flex items-center gap-2 px-4 py-2 rounded-lg border bg-card">
                <div className={`w-2 h-2 rounded-full ${systemStatus.milvus_collection_exists ? 'bg-green-500' : 'bg-red-500'}`} />
                <span className="text-sm font-medium">
                  {systemStatus.milvus_collection_exists ? 'System Online' : 'System Offline'}
                </span>
              </div>
            )}
          </motion.div>

          {metricsLoading ? (
            <div className="p-12 text-center">
              <div className="inline-block w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              <p className="mt-2 text-sm text-muted-foreground">Loading metrics...</p>
            </div>
          ) : metrics ? (
            <>
              {/* Stats Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <StatsCard
                  title="Total Documents"
                  value={metrics.total_documents}
                  icon={FileText}
                  delay={0}
                />
                
                <StatsCard
                  title="Total Queries"
                  value={metrics.total_queries}
                  description={`${metrics.queries_last_24h} in last 24h`}
                  icon={MessageSquare}
                  delay={0.1}
                />
                
                <StatsCard
                  title="Active Users"
                  value={metrics.total_users}
                  icon={Users}
                  delay={0.2}
                />
                
                <StatsCard
                  title="Avg Response Time"
                  value={formatLatency(Math.round(metrics.avg_latency_ms))}
                  icon={Clock}
                  delay={0.3}
                />

                {metrics.rag && (
                  <>
                    <StatsCard
                      title="Retrieval Hit Rate (7d)"
                      value={`${Math.round((metrics.rag.retrieval_hit_rate_7d ?? 0) * 100)}%`}
                      icon={TrendingUp}
                      delay={0.4}
                    />
                    <StatsCard
                      title="Grounded Answers (7d)"
                      value={`${Math.round((metrics.rag.grounded_rate_7d ?? 0) * 100)}%`}
                      icon={Activity}
                      delay={0.5}
                    />
                    <StatsCard
                      title="Avg Vector Distance (7d)"
                      value={
                        metrics.rag.avg_vector_distance_7d === null ||
                        typeof metrics.rag.avg_vector_distance_7d !== 'number'
                          ? '—'
                          : metrics.rag.avg_vector_distance_7d.toFixed(3)
                      }
                      icon={BarChart3}
                      delay={0.6}
                    />
                    <StatsCard
                      title="Hallucination Flags (7d)"
                      value={String(metrics.rag.hallucinations_7d ?? 0)}
                      icon={MessageSquare}
                      delay={0.7}
                    />
                  </>
                )}
              </div>

              {metrics.rag && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay: 0.35 }}
                  className="p-6 rounded-lg border bg-card"
                >
                  <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
                    <Activity className="w-5 h-5" />
                    RAG Telemetry
                  </h2>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="p-4 rounded-lg bg-muted/50 border">
                      <p className="text-sm text-muted-foreground mb-1">Tokens (24h)</p>
                      <p className="text-2xl font-bold">{metrics.rag.total_tokens_24h ?? 0}</p>
                    </div>
                    <div className="p-4 rounded-lg bg-muted/50 border">
                      <p className="text-sm text-muted-foreground mb-1">Estimated Cost (24h)</p>
                      <p className="text-2xl font-bold">
                        ${Number(metrics.rag.estimated_cost_usd_24h ?? 0).toFixed(4)}
                      </p>
                    </div>
                    <div className="p-4 rounded-lg bg-muted/50 border">
                      <p className="text-sm text-muted-foreground mb-1">Avg Retrieval Conf (24h)</p>
                      <p className="text-2xl font-bold">
                        {metrics.rag.avg_retrieval_confidence_24h === null ||
                        typeof metrics.rag.avg_retrieval_confidence_24h !== 'number'
                          ? '—'
                          : `${Math.round(metrics.rag.avg_retrieval_confidence_24h * 100)}%`}
                      </p>
                    </div>
                  </div>
                </motion.div>
              )}

              {/* Chart */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.4 }}
                className="p-6 rounded-lg border bg-card"
              >
                <h2 className="text-xl font-semibold mb-6 flex items-center gap-2">
                  <TrendingUp className="w-5 h-5" />
                  Query Activity (Last 7 Days)
                </h2>
                
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={metrics.queries_by_day}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                    <XAxis 
                      dataKey="date" 
                      className="text-xs"
                      tickFormatter={(date) => new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    />
                    <YAxis className="text-xs" />
                    <Tooltip 
                      contentStyle={{ 
                        backgroundColor: 'hsl(var(--card))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: '8px'
                      }}
                    />
                    <Line 
                      type="monotone" 
                      dataKey="count" 
                      stroke="hsl(var(--primary))" 
                      strokeWidth={2}
                      dot={{ fill: 'hsl(var(--primary))' }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </motion.div>

              {/* Documents by Type */}
              {Object.keys(metrics.documents_by_type).length > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, delay: 0.5 }}
                  className="p-6 rounded-lg border bg-card"
                >
                  <h2 className="text-xl font-semibold mb-6 flex items-center gap-2">
                    <Activity className="w-5 h-5" />
                    Documents by Type
                  </h2>
                  
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {Object.entries(metrics.documents_by_type).map(([type, count], index) => (
                      <div
                        key={type}
                        className="p-4 rounded-lg bg-muted/50 border"
                      >
                        <p className="text-sm text-muted-foreground mb-1 capitalize">{type}</p>
                        <p className="text-2xl font-bold">{count as number}</p>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}