package com.acme.pay;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class PaymentService {

    private static final Logger log = LoggerFactory.getLogger(PaymentService.class);

    public void charge(String account, long amountCents) {
        log.info("charging account={} amount={}", account, amountCents);
        if (amountCents <= 0) {
            // Concatenated message (no {} placeholders) and an ERROR for a routine
            // validation miss — an alert-fatigue smell with no correlation context.
            log.error("invalid amount for account " + account);
            return;
        }
        try {
            gateway().submit(account, amountCents);
        } catch (Exception e) {
            log.warn("charge retry for account={}", account, e);
        }
    }

    private Gateway gateway() {
        return new Gateway();
    }

    static final class Gateway {
        void submit(String account, long amountCents) {
            // network call to the payment gateway
        }
    }
}
