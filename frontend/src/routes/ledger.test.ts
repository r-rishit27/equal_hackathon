import { describe, expect, it } from 'vitest'
import { AR_UPLOAD_REVIEW_PATH, PATHS, isKnownRoute, ledgerForPath, pageForPath, titleForPath, arCustomerPath, arInvoicePath } from './paths'

describe('receivables routes', () => {
  it('puts every receivable page on the receivable side', () => {
    for (const p of [PATHS['ar-cash'], PATHS['ar-invoices'], PATHS['ar-upload'], PATHS['ar-customers'], AR_UPLOAD_REVIEW_PATH]) {
      expect(ledgerForPath(p)).toBe('receivable')
    }
  })

  it('keeps payable pages on the payable side and leaves shared pages neutral', () => {
    expect(ledgerForPath(PATHS.bills)).toBe('payable')
    expect(ledgerForPath(PATHS.upload)).toBe('payable')
    expect(ledgerForPath(PATHS.settings)).toBeNull()
  })

  it('does not confuse the payable and receivable upload pages', () => {
    expect(pageForPath(PATHS['ar-upload'])).toBe('ar-upload')
    expect(pageForPath(PATHS.upload)).toBe('upload')
    expect(pageForPath(AR_UPLOAD_REVIEW_PATH)).toBe('ar-upload')
  })

  it('accepts record deep links and titles them', () => {
    expect(isKnownRoute(arCustomerPath('c1'))).toBe(true)
    expect(isKnownRoute(arInvoicePath('i1'))).toBe(true)
    expect(isKnownRoute(AR_UPLOAD_REVIEW_PATH)).toBe(true)
    expect(titleForPath(PATHS['ar-cash'])).toMatch(/^Cash Application/)
  })
})
