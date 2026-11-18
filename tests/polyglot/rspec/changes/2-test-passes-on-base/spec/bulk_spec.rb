require_relative "../lib/shop/pricing"

RSpec.describe "bulk discount" do
  it "leaves a small order at full price" do
    expect(Shop::Pricing.total(250, 2)).to eq(500)
  end
end
