package com.acme.billing.jobs;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class InvoiceJobs {

    @Scheduled(cron = "0 0 2 * * *")
    public void nightlyInvoiceRun() {
        // generate invoices overnight
    }

    @Scheduled(fixedRate = 60000)
    public void pollPaymentStatus() {
        // poll the payment processor every minute
    }
}
