'use client';

import { useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { Upload, File, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { formatBytes } from '@/lib/utils';
import { cn } from '@/lib/utils';
import type { UploadItem } from '@/hooks/useDocuments';

interface DocumentUploaderProps {
  onUpload: (files: File[]) => void;
  isUploading?: boolean;
  uploadProgress?: number;
  uploadItems?: UploadItem[];
  maxFiles?: number;
}

export function DocumentUploader({
  onUpload,
  isUploading = false,
  uploadProgress = 0,
  uploadItems = [],
  maxFiles = 10,
}: DocumentUploaderProps) {
  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length > 0) {
        onUpload(acceptedFiles);
      }
    },
    [onUpload]
  );

  const { getRootProps, getInputProps, isDragActive, acceptedFiles, fileRejections } =
    useDropzone({
      onDrop,
      maxFiles,
      accept: {
        'application/pdf': ['.pdf'],
        'audio/*': ['.mp3', '.wav', '.m4a', '.flac'],
        'text/plain': ['.txt'],
        'text/markdown': ['.md'],
      },
      disabled: isUploading,
    });

  return (
    <div className="space-y-4">
      <div
        {...getRootProps()}
        className={cn(
          'relative border-2 border-dashed rounded-lg p-8 transition-colors cursor-pointer',
          isDragActive
            ? 'border-primary bg-primary/5'
            : 'border-border hover:border-primary/50 hover:bg-accent/50',
          isUploading && 'opacity-50 cursor-not-allowed'
        )}
      >
        <input {...getInputProps()} />
        
        <div className="flex flex-col items-center justify-center gap-4 text-center">
          <div className="p-3 rounded-full bg-primary/10">
            <Upload className="w-8 h-8 text-primary" />
          </div>

          {isUploading && uploadProgress > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="w-full max-w-sm space-y-2"
            >
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Uploading…</span>
                <span>{uploadProgress}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </motion.div>
          )}

          <div className="space-y-2">
            <p className="text-sm font-medium">
              {isDragActive ? 'Drop files here' : 'Drag & drop files here'}
            </p>
            <p className="text-xs text-muted-foreground">
              or click to browse
            </p>
            <p className="text-xs text-muted-foreground">
              Supports PDF, audio (MP3, WAV, M4A, FLAC), and text files
            </p>
          </div>
        </div>
      </div>

      {uploadItems.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-2"
        >
          <p className="text-sm font-medium">Upload status</p>
          <div className="space-y-2">
            {uploadItems.map((item) => {
              const StatusIcon =
                item.status === 'done'
                  ? CheckCircle2
                  : item.status === 'error'
                    ? AlertCircle
                    : item.status === 'uploading'
                      ? Loader2
                      : File;

              return (
                <div key={item.id} className="rounded-md border bg-card p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0">
                      <StatusIcon
                        className={cn(
                          'w-4 h-4 mt-0.5 flex-shrink-0',
                          item.status === 'done' && 'text-green-600',
                          item.status === 'error' && 'text-red-600',
                          item.status === 'uploading' && 'text-primary animate-spin',
                          item.status === 'pending' && 'text-muted-foreground'
                        )}
                      />
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{item.file.name}</p>
                        <p className="text-xs text-muted-foreground">{formatBytes(item.file.size)}</p>
                      </div>
                    </div>

                    <span className="text-xs text-muted-foreground capitalize">{item.status}</span>
                  </div>

                  <div className="mt-2 h-2 w-full rounded-full bg-muted overflow-hidden">
                    <div
                      className={cn(
                        'h-full transition-all',
                        item.status === 'error' ? 'bg-red-500' : 'bg-primary'
                      )}
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>

                  {item.error && (
                    <p className="mt-2 text-xs text-red-600">{item.error}</p>
                  )}
                </div>
              );
            })}
          </div>
        </motion.div>
      )}

      {acceptedFiles.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-2"
        >
          <p className="text-sm font-medium">
            {acceptedFiles.length} file{acceptedFiles.length !== 1 ? 's' : ''} selected
          </p>
          <div className="space-y-2">
            {acceptedFiles.map((file, index) => (
              <div
                key={index}
                className="flex items-center justify-between p-3 rounded-md bg-muted"
              >
                <div className="flex items-center gap-3">
                  <File className="w-4 h-4 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{file.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatBytes(file.size)}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {fileRejections.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="p-3 rounded-md bg-red-500/10 border border-red-500/20"
        >
          <p className="text-sm font-medium text-red-500">
            Some files were rejected:
          </p>
          <ul className="mt-2 text-xs text-red-500/80 list-disc list-inside">
            {fileRejections.map(({ file, errors }) => (
              <li key={file.name}>
                {file.name}: {errors.map((e) => e.message).join(', ')}
              </li>
            ))}
          </ul>
        </motion.div>
      )}
    </div>
  );
}