'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { Upload, FileText, MessageSquare, BarChart3, LogOut, CheckCircle2 } from 'lucide-react';
import Link from 'next/link';
import { useAuth } from '@/hooks/useAuth';
import { useDocuments } from '@/hooks/useDocuments';
import { Button } from '@/components/ui/Button';
import { DocumentUploader } from '@/components/documents/DocumentUploader';
import { DocumentTable } from '@/components/dashboard/DocumentTable';

export default function DashboardPage() {
  const { isAuthenticated, isLoading: authLoading, logout, user } = useAuth();
  const { documents, isLoading, uploadDocuments, isUploading, uploadProgress, uploadItems } = useDocuments();
  const [showSuccess, setShowSuccess] = useState(false);
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.push('/');
    }
  }, [isAuthenticated, authLoading, router]);

  const handleUpload = async (files: File[]) => {
    const result = await uploadDocuments(files);
    if (result.success) {
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 3000);
    }
  };

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
            <Button variant="secondary" className="w-full justify-start">
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

      {/* Main Content */}
      <div className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto p-8 space-y-8">
          {/* Header */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <h1 className="text-3xl font-bold mb-2">Document Management</h1>
            <p className="text-muted-foreground">
              Upload and manage your documents for AI-powered insights
            </p>
          </motion.div>

          {/* Success Message */}
          {showSuccess && (
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="p-4 rounded-lg bg-green-500/10 border border-green-500/20 flex items-center gap-3"
            >
              <CheckCircle2 className="w-5 h-5 text-green-600" />
              <p className="text-sm text-green-600 font-medium">
                Documents uploaded successfully!
              </p>
            </motion.div>
          )}

          {/* Upload Section */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.1 }}
            className="space-y-4"
          >
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold flex items-center gap-2">
                <Upload className="w-5 h-5" />
                Upload Documents
              </h2>
              {isUploading && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  Uploading...
                </div>
              )}
            </div>
            
            <DocumentUploader 
              onUpload={handleUpload}
              isUploading={isUploading}
              uploadProgress={uploadProgress}
              uploadItems={uploadItems}
            />
          </motion.div>

          {/* Documents List */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.2 }}
            className="space-y-4"
          >
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold flex items-center gap-2">
                <FileText className="w-5 h-5" />
                Your Documents
              </h2>
              <span className="text-sm text-muted-foreground">
                {documents.length} document{documents.length !== 1 ? 's' : ''}
              </span>
            </div>
            
            {isLoading ? (
              <div className="p-8 text-center border rounded-lg">
                <div className="inline-block w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                <p className="mt-2 text-sm text-muted-foreground">Loading documents...</p>
              </div>
            ) : (
              <DocumentTable documents={documents} />
            )}
          </motion.div>
        </div>
      </div>
    </div>
  );
}