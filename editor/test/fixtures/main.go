package main

import (
	"fmt"
	"strings"
)

func main() {
	words := []string{"a", "b"}
	raw := `a { raw string`
	r := '{'
	for i, w := range words {
		fmt.Println(i, strings.ToUpper(w), raw, r)
	}
}
