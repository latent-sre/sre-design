package com.acme.billing.web;

import com.acme.billing.repo.Invoice;
import com.acme.billing.repo.InvoiceRepository;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/invoices")
public class BillingController {

    private final InvoiceRepository invoiceRepository;

    public BillingController(InvoiceRepository invoiceRepository) {
        this.invoiceRepository = invoiceRepository;
    }

    @GetMapping("/{id}")
    public Invoice getInvoice(@PathVariable String id) {
        return invoiceRepository.findById(id).orElse(null);
    }
}
