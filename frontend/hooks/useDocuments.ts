import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { api, Document } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';

export type UploadStatus = 'pending' | 'uploading' | 'done' | 'error';

export interface UploadItem {
  id: string;
  file: File;
  progress: number;
  status: UploadStatus;
  error?: string;
}

export function useDocuments() {
  const queryClient = useQueryClient();
  const [uploadItems, setUploadItems] = useState<UploadItem[]>([]);

  const uploadProgress = useMemo(() => {
    if (uploadItems.length === 0) return 0;
    const total = uploadItems.reduce((acc, i) => acc + 100, 0);
    const done = uploadItems.reduce((acc, i) => acc + (i.progress ?? 0), 0);
    return Math.round((done / total) * 100);
  }, [uploadItems]);

  const { data: documents = [], isLoading, error } = useQuery({
    queryKey: queryKeys.documents.list(),
    queryFn: async () => {
      const response = await api.listDocuments();
      return response.documents as Document[];
    },
    refetchInterval: (query) => {
      const docs = (query.state.data as Document[]) || [];
      const hasOcrRunning = docs.some(
        (d) => d.ocr_status === 'queued' || d.ocr_status === 'running'
      );
      return hasOcrRunning ? 2000 : false;
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (files: File[]) => {
      const initial: UploadItem[] = files.map((file) => ({
        id: `${file.name}-${file.lastModified}-${file.size}`,
        file,
        progress: 0,
        status: 'pending',
      }));
      setUploadItems(initial);

      let hadError = false;

      for (const file of files) {
        const id = `${file.name}-${file.lastModified}-${file.size}`;
        setUploadItems((prev) =>
          prev.map((i) => (i.id === id ? { ...i, status: 'uploading', progress: 0, error: undefined } : i))
        );

        try {
          await api.uploadDocuments([file], (p) => {
            setUploadItems((prev) => prev.map((i) => (i.id === id ? { ...i, progress: p } : i)));
          });
          setUploadItems((prev) =>
            prev.map((i) => (i.id === id ? { ...i, status: 'done', progress: 100 } : i))
          );
        } catch (err: any) {
          hadError = true;
          const msg = err?.response?.data?.detail || err?.message || 'Upload failed';
          setUploadItems((prev) =>
            prev.map((i) => (i.id === id ? { ...i, status: 'error', error: msg } : i))
          );
        }
      }

      await queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
      return { hadError };
    },
  });

  const uploadDocuments = async (files: File[]) => {
    try {
      const result = await uploadMutation.mutateAsync(files);
      return { success: !result.hadError };
    } catch (err: any) {
      return { 
        success: false, 
        error: err.response?.data?.detail || 'Upload failed' 
      };
    }
  };

  return {
    documents,
    isLoading,
    error,
    uploadDocuments,
    isUploading: uploadMutation.isPending,
    uploadProgress,
    uploadItems,
  };
}