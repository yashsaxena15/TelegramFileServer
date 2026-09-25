import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api, PaginationMeta } from '@/lib/api';
import { apiFileToFileItem, FileItem } from '@/components/types';
import logger from '@/lib/logger';
import { handleApiError } from '@/lib/errorHandler';

export interface UseFilesResult {
    files: FileItem[];
    pagination?: PaginationMeta;
    isLoading: boolean;
    isFetching: boolean;
    isError: boolean;
    error: unknown;
    refetch: () => Promise<any>;
}

export const useFiles = (
    path: string = '/',
    page?: number,
    pageSize?: number,
    sortBy?: string,
    sortOrder?: string
): UseFilesResult => {
    const query = useQuery({
        queryKey: ['files', path, page, pageSize, sortBy, sortOrder],
        queryFn: async () => {
            logger.info("Fetching files", { path, page, pageSize, sortBy, sortOrder });
            try {
                const response = await api.fetchFiles(path, page, pageSize, sortBy, sortOrder);
                logger.info("Files fetched successfully", { 
                    path, 
                    count: response.files.length, 
                    pagination: response.pagination 
                });
                return {
                    files: response.files.map(apiFileToFileItem),
                    pagination: response.pagination,
                };
            } catch (error) {
                logger.error("Failed to fetch files", { path, error });
                handleApiError(error, 'network');
                throw error;
            }
        },
        placeholderData: keepPreviousData,
        staleTime: 1000 * 60 * 5, // 5 minutes
        refetchOnWindowFocus: true,
    });

    return {
        files: query.data?.files || [],
        pagination: query.data?.pagination,
        isLoading: query.isLoading,
        isFetching: query.isFetching,
        isError: query.isError,
        error: query.error,
        refetch: query.refetch,
    };
};