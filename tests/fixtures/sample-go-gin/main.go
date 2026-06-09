package main

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

func main() {
	r := gin.Default()

	// GET with a path param and a named handler.
	r.GET("/orders/:id", getOrder)

	// POST with an inline handler doing an http egress to the payments service.
	r.POST("/orders", func(c *gin.Context) {
		http.Get("http://payments/charge")
		c.Status(http.StatusCreated)
	})

	// A cache lookup must NOT be read as a route: "key" is not a "/"-path.
	cache.Get("key", &out)

	r.Run(":8080")
}

func getOrder(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"id": c.Param("id")})
}

func persistOrder(repo OrderRepo, o Order) {
	// The write error is discarded to the blank identifier — a logged-and-swallowed equivalent
	// (data loss): a failed persist is silently dropped.
	_, _ = repo.Write(o)
}
