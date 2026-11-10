package problem

import (
	"encoding/json"
	"net/http"
)

type Body struct {
	Type      string `json:"type"`
	Title     string `json:"title"`
	Status    int    `json:"status"`
	Code      string `json:"code"`
	Detail    string `json:"detail,omitempty"`
	RequestID string `json:"request_id,omitempty"`
	Upstream  string `json:"upstream,omitempty"`
}

func Write(w http.ResponseWriter, status int, code, title, detail, requestID string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(Body{
		Type: "urn:manufacture:problem:" + code, Title: title, Status: status,
		Code: code, Detail: detail, RequestID: requestID,
	})
}

func WriteUpstream(w http.ResponseWriter, status int, code, title, detail, requestID, upstream string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(Body{
		Type: "urn:manufacture:problem:" + code, Title: title, Status: status,
		Code: code, Detail: detail, RequestID: requestID, Upstream: upstream,
	})
}
