'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Pagination,
  PaginationContent,
  PaginationItem,
} from '@/components/ui/pagination';

interface AdminPaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

export function AdminPagination({ page, pageSize, total, onPageChange }: AdminPaginationProps) {
  const currentPage = Math.max(1, page);
  const totalItems = Math.max(0, total);
  const totalPages = Math.max(1, Math.ceil(totalItems / Math.max(1, pageSize)));
  const canGoPrevious = currentPage > 1;
  const canGoNext = currentPage < totalPages;

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-3 sm:flex-row sm:items-center sm:justify-between">
      <p aria-live="polite" className="font-mono text-xs text-muted-foreground">
        <span>Страница {currentPage} из {totalPages}</span>
        <span aria-hidden="true" className="px-2 text-border">·</span>
        <span>Всего: {totalItems}</span>
      </p>
      <Pagination aria-label="Пагинация списка" className="mx-0 w-auto justify-start sm:justify-end">
        <PaginationContent>
          <PaginationItem>
            <Button
              aria-label="Предыдущая страница"
              disabled={!canGoPrevious}
              onClick={() => canGoPrevious && onPageChange(currentPage - 1)}
              size="sm"
              variant="outline"
            >
              <ChevronLeft aria-hidden="true" className="h-4 w-4" />
              <span>Назад</span>
            </Button>
          </PaginationItem>
          <PaginationItem>
            <span
              aria-current="page"
              aria-label={`Страница ${currentPage}`}
              className="inline-flex h-8 min-w-8 items-center justify-center rounded-sm border border-primary/50 bg-primary/10 px-2 font-mono text-xs text-primary"
            >
              {currentPage}
            </span>
          </PaginationItem>
          <PaginationItem>
            <Button
              aria-label="Следующая страница"
              disabled={!canGoNext}
              onClick={() => canGoNext && onPageChange(currentPage + 1)}
              size="sm"
              variant="outline"
            >
              <span>Вперёд</span>
              <ChevronRight aria-hidden="true" className="h-4 w-4" />
            </Button>
          </PaginationItem>
        </PaginationContent>
      </Pagination>
    </div>
  );
}
