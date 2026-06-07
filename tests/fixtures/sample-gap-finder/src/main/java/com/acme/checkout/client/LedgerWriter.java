package com.acme.checkout.client;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
public class LedgerWriter {

    private static final Logger log = LoggerFactory.getLogger(LedgerWriter.class);
    private final LedgerRepository ledgerRepository;

    public LedgerWriter(LedgerRepository ledgerRepository) {
        this.ledgerRepository = ledgerRepository;
    }

    // PLANTED SWALLOW (non-messaging): a DB write whose failure is logged and dropped. The AST
    // swallow detector sees it, but the collectors only emit swallow facts for Kafka egress — so
    // the gap-finder is what surfaces it, and the engine re-deriving it graduates it to Tier-A.
    public void record(String orderId, long amountCents) {
        try {
            ledgerRepository.save(new Entry(orderId, amountCents));
        } catch (Exception e) {
            log.error("failed to record ledger entry for order {}", orderId, e);
        }
    }
}
