-- Add WAITING_TRIAGE to CaseStatus enum
ALTER TYPE "CaseStatus" ADD VALUE IF NOT EXISTS 'WAITING_TRIAGE' AFTER 'NEW';

-- Add new columns to cases table
ALTER TABLE "cases" ADD COLUMN IF NOT EXISTS "region" TEXT;
ALTER TABLE "cases" ADD COLUMN IF NOT EXISTS "budget_expectation" DOUBLE PRECISION;
ALTER TABLE "cases" ADD COLUMN IF NOT EXISTS "attachments" TEXT;
