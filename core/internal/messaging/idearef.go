package messaging

import (
	"fmt"

	"github.com/google/uuid"
)

// ManufactureNS is the UUIDv5 namespace for stable idea.* message_ids (D21).
var ManufactureNS = uuid.MustParse("b7e1f4a0-5c2d-4e8f-9a1b-0c3d5e7f9a1b")

// FormatIdeaRef returns the canonical business key idea:<id>:v<rev>.
func FormatIdeaRef(id int64, rev int) string {
	return fmt.Sprintf("idea:%d:v%d", id, rev)
}

// IdeaReadyMessageID is UUIDv5(NS, idea:<id>:v<rev>).
func IdeaReadyMessageID(id int64, rev int) uuid.UUID {
	return uuid.NewSHA1(ManufactureNS, []byte(FormatIdeaRef(id, rev)))
}

// IdeaStatusMessageID is UUIDv5(NS, idea:<id>:v<rev>:<status>:<production_id>).
func IdeaStatusMessageID(id int64, rev int, status string, productionID uuid.UUID) uuid.UUID {
	key := fmt.Sprintf("idea:%d:v%d:%s:%s", id, rev, status, productionID.String())
	return uuid.NewSHA1(ManufactureNS, []byte(key))
}
