package com.acme.order;

// A small, real source file the adversarial artifacts in this directory cite. Each planted
// artifact makes a claim that does NOT match what is actually here (the "pointer" an LLM
// enrichment got wrong); the deterministic challenge gate must catch every one of them.
public class InventoryClient {

    public void createOrder(OrderRequest req) {
        try {
            publisher.publish(new OrderCreated(req.id()));
        } catch (Exception e) {
            log.error("publish failed for {}", req.id());
            throw new IllegalStateException("publish failed", e);
        }
    }

    public Inventory reserve(String sku) {
        return inventory.lookup(sku);
    }
}
